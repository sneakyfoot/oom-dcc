# 3DE4.script.name: OOM Load
# 3DE4.script.gui: Main Window::OOM
# 3DE4.script.comment: Loads the latest project version.
import os


# Requester identifiers
REQUESTER_LABEL_WIDGET = 'oom_version_label'
REQUESTER_MENU_WIDGET = 'oom_version_menu'

# Set in startup script, here to keep linter from yelling at me
tk = tk
sg = sg
engine = engine
project = project
context = context
shot = shot
tde4 = tde4

# TODO: Allow user input for the load name
# Using a default name for now
load_name = 'Tracking'

# Shotgun stuff
pipeline_step = 'TRK'
pipeline_step_long = 'Tracking'
dir_template = tk.templates.get('oom_3de_dir')
file_template = tk.templates.get('oom_3de_file')

# Get step and task id's
step_id = sg.find_one('Step', [["code", "is", pipeline_step_long]], ["code", "name"])

task_filters = [
    ['project', 'is', context.project],
    ['entity', 'is', context.entity],
    ['step', 'is', step_id]
]

task_id = sg.find_one('Task', task_filters, ['content', 'name'])

# Populate template fields


def build_load_fields():
    fields = context.as_template_fields(file_template)
    fields['Step'] = pipeline_step
    fields['name'] = load_name
    return fields


# Collect saved version paths
fields = build_load_fields()
all_versions = tk.paths_from_template(file_template, fields, skip_keys=['version'])

version_candidates = []
for path in all_versions:
    if not os.path.exists(path):
        continue

    try:
        v_fields = file_template.get_fields(path)
        raw_version = v_fields.get('version', 0)

        version = int(raw_version)
        version_candidates.append((version, path))

    except (TypeError, ValueError):
        print('Skipped saved file with invalid version "{}": {}'.format(raw_version, path))
    except Exception:
        continue

# Version selection UI

def prompt_user_for_version(sorted_candidates):

    # Build requester with a list of available versions
    requester = tde4.createCustomRequester()

    if requester is None:
        print('Failed to create version chooser requester.')
        return None

    try:
        label = 'Pick a saved version to load'
        tde4.addLabelWidget(requester, REQUESTER_LABEL_WIDGET, label, 'ALIGN_LABEL_LEFT')

        menu_order = list(reversed(sorted_candidates))

        display_items = []
        label_map = {}

        for version, path in menu_order:
            basename = os.path.basename(path)
            display_label = 'v{:04d}  {}'.format(version, basename)
            display_items.append(display_label)
            label_map[display_label] = (version, path)

        if not display_items:
            print('No display items available for version chooser.')
            return None

        default_label = display_items[0]
        default_index = 1

        tde4.addOptionMenuWidget(requester, REQUESTER_MENU_WIDGET, '', *display_items)

        try:
            tde4.setWidgetValue(requester, REQUESTER_MENU_WIDGET, default_label)
        except Exception:
            tde4.setWidgetValue(requester, REQUESTER_MENU_WIDGET, default_index)

        window_title = 'Load OOM Version'
        button = tde4.postCustomRequester(requester, window_title, 420, 300, 'Load', 'Cancel')

        if isinstance(button, str):
            if button.lower() != 'load':
                return None
        elif isinstance(button, int):
            if button < 0:
                return None
        else:
            return None

        selected_value = tde4.getWidgetValue(requester, REQUESTER_MENU_WIDGET)

        if isinstance(selected_value, int):
            selected_index = selected_value - 1
        elif isinstance(selected_value, str):
            if selected_value in label_map:
                return label_map[selected_value]

            if selected_value.isdigit():
                selected_index = int(selected_value) - 1
            else:
                return None
        else:
            return None

        if 0 <= selected_index < len(menu_order):
            return menu_order[selected_index]

        return None

    except Exception:
        return None

    finally:
        try:
            tde4.unpostCustomRequester(requester)
        except Exception:
            pass

        tde4.deleteCustomRequester(requester)


# Resolve chosen version

def resolve_version_to_load(candidates):

    # Allow the artist to choose, but fall back to the latest version
    sorted_candidates = sorted(candidates)
    chosen = prompt_user_for_version(sorted_candidates)

    if chosen is None:
        latest_version, _ = sorted_candidates[-1]
        print('No version picked, loading the latest saved version (v{:04d}).'.format(latest_version))
        chosen = sorted_candidates[-1]

    return chosen


if not version_candidates:
    print('No saved versions found to load for {}'.format(load_name))
else:
    load_version, load_path = resolve_version_to_load(version_candidates)

    # Load project
    tde4.loadProject(load_path)
    print('Loaded version {} for task {}'.format(load_version, task_id))
