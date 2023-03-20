from pcbnew import *

from .board_modifier import BoardModifier


class TemplateCopier(BoardModifier):
    def __init__(self, logger, board, template_path, route_tracks):
        super().__init__(logger, board)
        self.__template = LoadBoard(template_path)
        self.__board_nets_by_name = board.GetNetsByName()
        self.__route_tracks = route_tracks

    # Copy positions of elements and tracks from template to board.
    # This method does not copy parts itself - parts to be positioned need to be present in board
    # prior to calling this.
    def run(self):
        footprints = self.__template.GetFootprints()

        for footprint in footprints:
            reference = footprint.GetReference()
            destination_footprint = self.get_footprint(reference)

            layer = footprint.GetLayerName()
            position = footprint.GetPosition()
            orientation = footprint.GetOrientation()

            if layer == "B.Cu" and destination_footprint.GetLayerName() != "B.Cu":
                destination_footprint.Flip(destination_footprint.GetCenter(), False)
            self.set_position(destination_footprint, position)
            destination_footprint.SetOrientation(orientation)

        if self.__route_tracks:
            tracks = self.__template.GetTracks()
            for track in tracks:
                # clone track but remap netinfo because net codes in template might be different.
                # use net names for remmaping (names in template and bourd under modification must match)
                clone = track.Duplicate()
                net_name = clone.GetNetname()
                net_code = clone.GetNetCode()
                net_info_in_board = self.__board_nets_by_name[net_name]
                self.logger.info(
                    f"Cloning track from template: {net_name}:{net_code}"
                    f"-> {net_info_in_board.GetNetname()}:{net_info_in_board.GetNetCode()}",
                )
                clone.SetNet(net_info_in_board)
                self.board.Add(clone)
