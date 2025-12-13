import os, yaml
root = "/mnt/RAID/Assets/shotgun"               # descriptor path you set
pc_yml = os.path.join(root, "pipeline_configuration.yml")
print("File exists :", os.path.exists(pc_yml))
if os.path.exists(pc_yml):
    with open(pc_yml) as fh:
        data = yaml.safe_load(fh) or {}
    print("YAML keys  :", list(data.keys()))
    for k in ("project_name", "project_id", "project_disk_name"):
        print(k, "=", data.get(k))

