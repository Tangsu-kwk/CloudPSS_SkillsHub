"""Read-only functions from the bundled automodeling 0.1.0 SDK."""
from .component_model import _error_diagnostics


class RemoteReadError(RuntimeError):
    def __init__(self, message, graphql_errors=None):
        super().__init__(message)
        self.graphql_errors = graphql_errors


def _request(query, variables, requester=None):
    if requester is None:
        from cloudpss.utils import graphql_request
        requester = graphql_request
    try:
        response = requester(query, variables, timeout=30)
    except Exception as exc:
        # SDK raises HTTPError before parsing GraphQL validation errors (400).
        # Preserve structured service diagnostics; never expose request headers.
        try:
            response=exc.response.json()
        except Exception:
            response=None
        if not isinstance(response,dict) or not response.get('errors'):
            raise RemoteReadError("GraphQL request failed; check connectivity, API URL and API token") from None
    if not isinstance(response, dict):
        raise RemoteReadError("Invalid GraphQL response")
    if response.get("errors"):
        raise RemoteReadError("GraphQL returned errors", _error_diagnostics(response["errors"]))
    if not isinstance(response.get("data"), dict):
        raise RemoteReadError("Invalid GraphQL response: missing data")
    return response["data"]
