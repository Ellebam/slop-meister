"""Small helpers shared by the browser runtime tests."""

CONNECT = "chrome-extension://abc/connect.html?mcpRelayUrl=x&token=dummy-private-token"


def commands(calls):
    return [next(a for a in argv if not a.startswith("-")) for argv, _ in calls]
