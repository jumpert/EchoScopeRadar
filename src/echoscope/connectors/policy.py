from datetime import timedelta

from echoscope.domain.models import utcnow
from echoscope.domain.rules import evaluate

from .syndication import parse_date


def publication_selected(request, title, published):
    if published and published < utcnow() - timedelta(days=request.source.initial_days):
        return False
    return request.source.tracking == "owned" or any(
        match.confirmed for match in evaluate(title or "", request.rules)
    )


def current_targets(targets, source):
    now = utcnow()
    result = {}
    for identifier, target in targets.items():
        date = parse_date(target.get("published") or target.get("seen"))
        if date is None or date >= now - timedelta(days=source.follow_days):
            result[identifier] = target
    return result
