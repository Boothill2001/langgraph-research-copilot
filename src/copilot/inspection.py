"""Separate workflow progress from intentional inspection of historical executions."""


def execution_choices(events, node=None):
    return [event for event in events if node is None or event["node"] == node]


def current_execution(events, follow_latest=True, node=None, event_id=None):
    if follow_latest:
        return events[-1] if events else None
    choices = execution_choices(events, node)
    if not choices:
        return None
    return next((event for event in choices if event["id"] == event_id), choices[-1])
