import logging

import pcbnew

from .board_modifier import get_footprint, set_position

logger = logging.getLogger(__name__)


def copy_from_template_to_board(
    board: pcbnew.BOARD,
    template_path: str,
    route_tracks: bool,
) -> None:
    """Copy positions of elements and tracks from template to board.
    This method does not copy parts itself - parts to be positioned
    need to be present in board prior to calling this.
    """
    template = pcbnew.LoadBoard(template_path)
    footprints = template.GetFootprints()
    board_nets_by_name = board.GetNetsByName()

    for footprint in footprints:
        reference = footprint.GetReference()
        destination_footprint = get_footprint(board, reference)

        layer = footprint.GetLayerName()
        position = footprint.GetPosition()
        orientation = footprint.GetOrientation()

        if layer == "B.Cu" and destination_footprint.GetLayerName() != "B.Cu":
            destination_footprint.Flip(destination_footprint.GetCenter(), False)
        set_position(destination_footprint, position)
        destination_footprint.SetOrientation(orientation)

    if route_tracks:
        tracks = template.GetTracks()
        for track in tracks:
            # Clone track but remap netinfo because net codes in template
            # might be different. Use net names for remapping
            # (names in template and board under modification must match)
            clone = track.Duplicate()
            net_name = clone.GetNetname()
            net_code = clone.GetNetCode()
            net_info_in_board = board_nets_by_name[net_name]
            logger.info(
                f"Cloning track from template: {net_name}:{net_code}"
                f"-> {net_info_in_board.GetNetname()}:"
                f"{net_info_in_board.GetNetCode()}",
            )
            clone.SetNet(net_info_in_board)
            board.Add(clone)
