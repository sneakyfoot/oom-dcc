import hou
import os


def sync_cut_range():
    try:
        tk = hou.session.oom_tk
        context = hou.session.oom_context
        sg = tk.shotgun
        entity = context.entity if context else None
        shot_id = entity.get("id") if entity else None
        if not shot_id:
            raise RuntimeError("No shot context found")

        shot = sg.find_one(
            "Shot",
            [["id", "is", shot_id]],
            ["sg_cut_in", "sg_cut_out"],
        )
        if not shot:
            raise RuntimeError("Shot not found in ShotGrid")

        cut_in = shot.get("sg_cut_in")
        cut_out = shot.get("sg_cut_out")
        if cut_in is None or cut_out is None:
            raise RuntimeError("Cut range missing on ShotGrid")

        hou.playbar.setFrameRange(cut_in, cut_out)
        hou.playbar.setPlaybackRange(cut_in, cut_out)
        os.environ["CUT_IN"] = str(cut_in)
        os.environ["CUT_OUT"] = str(cut_out)
        print(f"[oom] Synced playbar to cut range {cut_in}-{cut_out}")
    except Exception as e:
        hou.ui.displayMessage(f"Failed to sync cut range: {e}")


def launch():
    sync_cut_range()


launch()
