from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from weblate.addons.base import BaseAddon
from weblate.addons.events import EVENT_COMPONENT_UPDATE
from weblate.trans.models import Change
from weblate.utils.state import STATE_FUZZY, STATE_TRANSLATED


class GravityAddon(BaseAddon):
    events = (EVENT_COMPONENT_UPDATE,)
    name = "weblate.gravity.custom"
    verbose = 'Flag changed source or target strings as "Needs editing"'
    description = (
        "Whenever a changed translatable string is imported from the VCS, "
        "it is flagged as needing editing in Weblate. This way you can easily"
        "filter and edit translations changed by the developers."
    )
    user_name = "gravity"
    user_verbose = "Gravity addon"

    def component_update(self, component):
        applied_addons_changes = component.change_set.filter(
            action=Change.ACTION_ADDON_CREATE
        ).order_by("-id")

        analyze_from_id = None
        analyze_from_date = timezone.now().date() - timedelta(minutes=10)
        changes_filter = Q(timestamp__date__gte=analyze_from_date)

        if applied_addons_changes.exists():
            analyze_from_id = applied_addons_changes[0].id
            changes_filter = changes_filter & Q(id__gt=analyze_from_id)
        else:
            print("Not found addons applying. Maybe this is new component.")

        for translation in component.translation_set.iterator():
            units = translation.unit_set.filter(
                last_updated__date__gte=analyze_from_date,
                state__gte=STATE_TRANSLATED
            )

            for unit in units:
                changes = unit.change_set.filter(changes_filter).order_by("-id")

                last_change_from_repo = changes.exists() and changes[0].action == Change.ACTION_STRING_REPO_UPDATE

                if last_change_from_repo:
                    unit.translate(self.user, unit.target, STATE_FUZZY, propagate=False)