"""Drive the unmodified SimBot through user messages and retain audit evidence.

Commands are local JSON files: message, fresh, stop. Snapshots only observe the
model; they never repair it or inject model/template data into the conversation.
"""
from __future__ import annotations
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('OPENHANDS_SUPPRESS_BANNER', '1')
import newagentv2 as host
from openhands.sdk import Conversation
from openhands.sdk.conversation.response_utils import get_agent_final_response

OUT = ROOT / 'testing' / 'runs' / '20260907-user-dialogue'
INBOX = OUT / 'inbox'
INBOX.mkdir(parents=True, exist_ok=True)
SECRETS = [os.environ.get(k, '') for k in ('LLM_API_KEY', 'SIMSTUDIO_TOKEN', 'CLOUDPSS_TOKEN')]

def clean(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    for secret in SECRETS:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text

def save(path, value):
    path.write_text(clean(value), encoding='utf-8')

conversation = None
session = ''
event_path = None

def on_event(event):
    value = event.model_dump(mode='json') if hasattr(event, 'model_dump') else str(event)
    with event_path.open('a', encoding='utf-8') as f:
        f.write(clean({'observed_at': time.time(), 'event': value}) + '\n')

def fresh(name):
    global conversation, session, event_path
    if conversation is not None:
        conversation.close()
    host.WORKFLOW_STATE = host.WorkflowState()
    session = name
    event_path = OUT / (name + '-events.jsonl')
    conversation = Conversation(agent=host.create_agent(), workspace=ROOT,
                                callbacks=[on_event], visualizer=None,
                                max_iteration_per_run=35)

save(OUT / 'ready.json', {'ready': True, 'pid': os.getpid()})
print('PROBE_READY', flush=True)
while True:
    pending = sorted(INBOX.glob('*.json'))
    if not pending:
        time.sleep(0.5)
        continue
    path = pending[0]
    command = json.loads(path.read_text(encoding='utf-8-sig'))
    command_id = path.stem
    path.rename(path.with_suffix('.processing'))
    started = time.time()
    try:
        if command.get('stop'):
            if conversation:
                conversation.close()
            break
        if command.get('fresh'):
            fresh(command['fresh'])
        if conversation is None:
            fresh('initial')
        message = command.get('message')
        response = ''
        if message:
            turn = host.WORKFLOW_STATE.begin_turn()
            conversation.send_message(message)
            conversation.run()
            response = get_agent_final_response(list(conversation.state.events)) or ''
        state = host.WORKFLOW_STATE.skill_sessions.get('cloudpss-aux-modeling', {})
        model = state.get('memory_model')
        if model is not None:
            save(OUT / (command_id + '-model.json'), model.toJSON())
        result = {'id': command_id, 'session': session, 'message': message,
                  'response': response, 'elapsed_s': time.time() - started,
                  'pending_preview': state.get('pending_preview'),
                  'original_rid': state.get('original_rid'),
                  'has_memory_model': model is not None}
        save(OUT / (command_id + '-result.json'), result)
        print('DONE ' + command_id, flush=True)
    except Exception:
        save(OUT / (command_id + '-result.json'), {'id': command_id,
             'error': traceback.format_exc(), 'elapsed_s': time.time() - started})
        print('ERROR ' + command_id, flush=True)
    path.with_suffix('.processing').rename(path.with_suffix('.done'))
