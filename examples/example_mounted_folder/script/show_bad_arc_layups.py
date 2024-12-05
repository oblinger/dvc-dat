__main__ = {
  "dat": {
    "do": "shot_visualizer"   # code used to run visualizer plus some defaults
                              # also specifies baller10 as default input
  },
  "vis": {
    "show_shot_arc": True,
    "filter_do": "bad_arc_layups.filter_fn"
  }
}


def filter_fn(align):
    return "layup" in align.scores and align.ui.player_id != align.ai.player_id
