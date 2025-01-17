from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from weblate.addons.base import BaseAddon
from weblate.addons.events import AddonEvent
from weblate.trans.models import Change, Component
from weblate.utils.state import STATE_FUZZY, STATE_TRANSLATED


def get_component_translations_in_master(component):
    component_translations_in_master = defaultdict(dict)

    # find master category in project (main category doesn't have __ in name)
    master_category = component.project.category_set.filter(
        ~Q(name__contains="__")
    ).first()

    if not master_category:
        return component_translations_in_master

    component_name = component.name.split("__")[0]
    component_in_master_category = Component.objects.filter(
        category=master_category,
        name=component_name
    ).first()

    if not component_in_master_category:
        return component_translations_in_master

    for translation in component_in_master_category.translation_set.iterator():
        units = translation.unit_set.all()

        for unit in units:
            component_translations_in_master[translation.language_code][unit.checksum] = unit.get_target_plurals()

    return component_translations_in_master


def fix_newline(filename):
    """Add missed EOL to file."""

    with open(filename, 'r+') as f:
        f.seek(0, 2)
        f.seek(f.tell() - 1, 0)
        last_char = f.read(1)
        if last_char != '\n':
            f.write('\n')


class GravityAddon(BaseAddon):
    events = (AddonEvent.EVENT_COMPONENT_UPDATE, AddonEvent.EVENT_PRE_COMMIT,)
    name = "weblate.gravity.custom"
    verbose = 'Flag changed source or target strings as "Needs editing"'
    description = (
        "Whenever a changed translatable string is imported from the VCS, "
        "it is flagged as needing editing in Weblate. This way you can easily"
        "filter and edit translations changed by the developers."
    )
    user_name = "gravity"
    user_verbose = "Gravity addon"
    trigger_update = True

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

        if not component.category or "__" not in component.category.name:
            print("Component dont have category or in main category")
            return

        approved_translations_in_master = get_component_translations_in_master(component)

        # The main language should be processed first
        # This is necessary because when processing keys from secondary languages, their status in the main language is checked
        # Accordingly, the key processing of the main language should be carried out first
        translations = sorted(
            component.translation_set.all(),
            key=lambda x: x.is_source,
            reverse=True
        )

        for translation in translations:
            units = translation.unit_set.filter(last_updated__date__gte=analyze_from_date)

            for unit in units:
                value_in_master = approved_translations_in_master.get(
                    translation.language_code,
                    {}
                ).get(unit.checksum, None)

                is_equal_to_master = unit.get_target_plurals() == value_in_master

                if is_equal_to_master:
                    if unit.state < STATE_TRANSLATED:
                        # Confirm the translation in the main language
                        if translation.is_source:
                            unit.translate(self.user, unit.target, STATE_TRANSLATED, propagate=False)
                        # In a secondary language, we confirm the translation only if it is confirmed in the primary language
                        elif unit.source_unit.state >= STATE_TRANSLATED:
                            unit.translate(self.user, unit.target, STATE_TRANSLATED, propagate=False)
                    else:
                        # In the secondary language, we remove the confirmation from the translation if it is not confirmed in the main language
                        if not translation.is_source and unit.source_unit.state < STATE_TRANSLATED:
                            unit.translate(self.user, unit.target, STATE_FUZZY, propagate=False)

                elif unit.state >= STATE_TRANSLATED:
                    # TODO check only content change
                    changes = unit.change_set.filter(changes_filter).order_by("-id")
                    last_change_from_repo = changes.exists() and changes[0].action in [
                        Change.ACTION_STRING_REPO_UPDATE,
                        Change.ACTION_NEW_UNIT_REPO
                    ]

                    if last_change_from_repo:
                        unit.translate(self.user, unit.target, STATE_FUZZY, propagate=False)

        count_pending = component.count_pending_units
        if count_pending:
            component.commit_pending("add-on", None)

    def pre_commit(self, translation, author):
        fix_newline(translation.get_filename())
