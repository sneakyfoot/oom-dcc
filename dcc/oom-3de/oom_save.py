# 3DE4.script.name: OOM Save
# 3DE4.script.gui: Main Window::OOM
# 3DE4.script.comment: Saves the current project.
import os,time

# Set in startup script, here to keep linter from yelling at me
tk = tk
sg = sg
engine = engine
project = project
context = context
shot = shot

# TODO: Allow user input for the save name
# Using a default name for now
save_name = 'Tracking'
default_version = 1

# Shotgun stuff
pipeline_step = 'TRK'
pipeline_step_long = 'Tracking'
dir_template = tk.templates.get("oom_3de_dir")
file_template = tk.templates.get("oom_3de_file")

# Get step and task id's
step_id = sg.find_one("Step",[["code", "is", pipeline_step_long]],["code", "name"])

task_filters = [
    ["project", "is", context.project],
    ["entity", "is", context.entity],
    ["step", "is", step_id]
]

task_id = sg.find_one("Task", task_filters, ["content", "name"])

# Populate template fields
def build_save_fields(save_version, save_name):
    fields = context.as_template_fields(file_template)
    fields["Step"] = pipeline_step
    fields["name"] = save_name
    fields["version"]= save_version
    return fields

# build default path
default_fields = build_save_fields(default_version,save_name)
default_path = file_template.apply_fields(default_fields)

# Check existing versions
check_fields = file_template.get_fields(default_path)
all_versions = tk.paths_from_template(file_template,check_fields,skip_keys=["version"])

version_numbers = []
for p in all_versions:
    try:
        v_fields = file_template.get_fields(p)
        version_numbers.append(v_fields.get("version", 0))
    except:
        pass

save_version = max(version_numbers) + 1 if version_numbers else 1

# build path
fields = build_save_fields(save_version,save_name)
save_path = file_template.apply_fields(fields)
dir_path = os.path.dirname(save_path)

# Save project
os.makedirs(dir_path,exist_ok=True)
tde4.saveProject(save_path)
print(task_id)
# Publish to shotgun
pft = sg.find_one("PublishedFileType", [["code", "is", "oom_3de_file"]])
publish_data = {
    "project": project,
    "entity": {"type": context.entity["type"], "id": context.entity["id"]},
    "task": task_id,
    "path": {"local_path": save_path},
    "name": save_name,
    "code": save_name,
    "version_number": save_version,
    "published_file_type": pft 
}

published_file = sg.create("PublishedFile", publish_data)
