"""Run a serial SimBot smoke test on a pinned SkillsHub commit."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SimBot:
    def __init__(self, base_url, token):
        url = urlparse(base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("SIMBOT_URL must be an HTTP(S) server URL")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = build_opener(NoRedirect())

    def request(self, path, *, data=None, query=None, session_key=None):
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query, doseq=True)
        auth = {"X-Session-API-Key": session_key} if session_key else {"X-Access-Token": self.token}
        request = Request(url, headers={**auth, "Content-Type": "application/json"},
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            with self.opener.open(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"{request.get_method()} {path}: HTTP {error.code}") from None
        except TimeoutError:
            raise RuntimeError(f"{request.get_method()} {path} timed out; inspect the existing conversation before retrying") from None

    def conversation(self, cid):
        return self.request("/api/v1/app-conversations", query={"ids": cid})[0]

    def sandbox(self, cid):
        conversation = self.conversation(cid)
        target = urlparse(conversation["conversation_url"])
        base = urlparse(self.base_url)
        if (target.scheme, target.netloc) != (base.scheme, base.netloc):
            raise RuntimeError("Sandbox API URL has a different origin from SIMBOT_URL")
        return target.path, conversation["session_api_key"]

    def events(self, path, session_key, start=None):
        query = {"limit": 100, "exclude_full_state": "true"}
        if start:
            query["timestamp__gte"] = start
        items = []
        while True:
            page = self.request(f"{path}/events/search", query=query, session_key=session_key)
            items.extend(page["items"])
            if not page.get("next_page_id"):
                return items
            query["page_id"] = page["next_page_id"]


def wait_for(check, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := check():
            return value
        time.sleep(5)
    raise TimeoutError("SimBot did not reach the expected state within the timeout")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def launch(client, profile, commit, prompt, evidence, sandbox_id):
    payload = {
        "agent_profile_id": profile,
        "title": f"Short circuit smoke test {commit[:8]}",
        "public": False,
        "generate_title_on_submit": False,
        "system_message_suffix": prompt,
        "trigger": "automation",
    }
    if sandbox_id:
        payload["sandbox_id"] = sandbox_id
    else:
        payload["plugins"] = [{"source": "github:Tangsu-kwk/CloudPSS_SkillsHub", "ref": commit}]
    task = client.request("/api/v1/app-conversations", data=payload)
    task_id = task["id"]
    write_json(evidence / "launch.json", {"commit": commit, "start_task_id": task_id, "profile_id": profile})

    def started():
        item = client.request("/api/v1/app-conversations/start-tasks", query={"ids": task_id})[0]
        if item["status"] == "ERROR":
            raise RuntimeError(f"SimBot launch failed for start task {task_id}")
        return item.get("app_conversation_id") if item["status"] == "READY" else None

    return wait_for(started, 240)


def run_turn(client, path, session_key, text, timeout, target):
    state = client.request(path, session_key=session_key)
    if state.get("execution_status") not in {"idle", "finished"}:
        raise RuntimeError("The test conversation must be available before sending a new message")
    previous = client.events(path, session_key)
    previous_ids = {item["id"] for item in previous}
    start = previous[-1]["timestamp"] if previous else None
    client.request(f"{path}/events", data={"content": [{"type": "text", "text": text}], "run": False},
                   session_key=session_key)
    client.request(f"{path}/run", data={}, session_key=session_key)

    def completed():
        events = [item for item in client.events(path, session_key, start) if item["id"] not in previous_ids]
        # System prompts, secret-bearing setup events, and model traces are not required here.
        records = [{key: item[key] for key in ("id", "timestamp", "kind", "source", "activated_skills") if key in item}
                   for item in events]
        for record, event in zip(records, events):
            if event.get("tool_name") == "invoke_skill" and event["kind"] == "ActionEvent":
                record["invoked_skill"] = event.get("action", {}).get("name")
        write_json(target, records)
        state = client.request(path, session_key=session_key).get("execution_status")
        if state in {"error", "stuck", "paused", "waiting_for_confirmation", "deleting"}:
            raise RuntimeError(f"SimBot stopped in state {state}")
        messages = [item for item in events if item["kind"] == "MessageEvent" and item.get("source") == "agent"]
        user_turns = [item for item in events if item["kind"] == "MessageEvent" and item.get("source") == "user"]
        if len(user_turns) > 1:
            raise RuntimeError("Multiple user messages arrived during the test turn")
        return messages[-1] if len(user_turns) == 1 and messages and state in {"idle", "finished"} else None

    return wait_for(completed, timeout)


def read_artifact(client, cid, path):
    file_data = client.request(f"/api/v1/app-conversations/{cid}/file", query={"file_path": path})
    if not file_data:
        raise RuntimeError(f"Missing expected test artifact {path}")
    return file_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--commit", required=True, help="Full SHA of the branch commit on GitHub")
    parser.add_argument("--scenario", type=Path, required=True, help="JSON with turns, optional expected skill, and files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, help="Prompt variant to test with the same Skill commit")
    parser.add_argument("--sandbox-id", help="Reuse an isolated sandbox with the branch Skill package installed")
    parser.add_argument("--launch-record", type=Path, help="Resume a prepared conversation before sending its first test turn")
    parser.add_argument("--timeout", type=int, default=240, help="Seconds per turn")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("--commit must be a full Git SHA")
    scenario = json.loads(args.scenario.read_text(encoding="utf-8-sig"))
    if not 1 <= len(scenario["turns"]) <= 8:
        parser.error("Specify one to eight sequential turns")
    root = Path(__file__).resolve().parents[1]
    prompt = (args.prompt or root / "docs/short-circuit/agent-prompt.md").read_text(encoding="utf-8-sig")
    client = SimBot(os.environ["SIMBOT_URL"], os.environ["SIMBOT_API_TOKEN"])
    args.output.mkdir(parents=True, exist_ok=False)
    if args.launch_record:
        record = json.loads(args.launch_record.read_bytes())
        if record["commit"] != args.commit:
            parser.error("Launch record commit differs from --commit")
        cid = record["conversation_id"]
        path, session_key = client.sandbox(cid)
        if any(item.get("source") == "user" and item["kind"] == "MessageEvent"
               for item in client.events(path, session_key)):
            raise RuntimeError("The prepared conversation already has user turns")
    else:
        cid = launch(client, args.profile, args.commit, prompt, args.output, args.sandbox_id)
        path, session_key = client.sandbox(cid)
    write_json(args.output / "conversation.json", {"conversation_id": cid, "commit": args.commit,
                                                   "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
    print(f"SimBot conversation {cid}", flush=True)
    state = client.request(path, session_key=session_key, query={"include_skills": "true"})
    workspace = state["workspace"]["working_dir"]
    context = state["agent"]["agent_context"]
    skills = context["skills"]
    if not skills and context["load_project_skills"]:
        skills_path = path.rsplit("/api/conversations/", 1)[0] + "/api/skills"
        skills = client.request(skills_path, session_key=session_key, data={
            "load_public": False, "load_user": False, "load_org": False,
            "load_project": True, "project_dir": workspace,
        })["skills"]
    # Keep names only. Skill bodies may include environment-specific instructions.
    skill_rows = skills.get("skills", []) if isinstance(skills, dict) else skills
    names = {item["name"] if isinstance(item, dict) else item for item in skill_rows}
    write_json(args.output / "skills.json", sorted(names))
    required = {"cloudpss-aux-modeling", "short-circuit-analysis"}
    if not required.issubset(names):
        raise RuntimeError(f"Expected skills missing: {sorted(required - names)}")
    for index, turn in enumerate(scenario["turns"], 1):
        target = args.output / f"turn-{index}.json"
        message = run_turn(client, path, session_key, turn["message"], args.timeout, target)
        if skill := turn.get("skill"):
            if not any(skill == item.get("invoked_skill") or skill in (item.get("activated_skills") or [])
                       for item in json.loads(target.read_bytes())):
                raise RuntimeError(f"Turn {index}: did not observe activation of {skill}")
        write_json(args.output / f"turn-{index}-reply.json", message["llm_message"]["content"])
        for number, path in enumerate(turn.get("files", []), 1):
            data = read_artifact(client, cid, path)
            (args.output / f"turn-{index}-artifact-{number}").write_text(data, encoding="utf-8")
        print(f"SimBot turn {index} checked", flush=True)
    write_json(args.output / "result.json", {"status": "passed", "turns": len(scenario["turns"]), "conversation_id": cid})


if __name__ == "__main__":
    main()
