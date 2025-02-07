# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from appPreProcessor import *


class line_xyz(PreProc):

    include_header = True
    coordinate_format = "%.*f"
    feedrate_format = "%.*f"

    def start_code(self, p):
        units = " " + str(p["units"]).lower()
        coords_xy = p["xy_toolchange"]
        end_coords_xy = p["end_xy"]
        gcode = ""

        xmin = "%.*f" % (p.coords_decimals, p["options"]["xmin"])
        xmax = "%.*f" % (p.coords_decimals, p["options"]["xmax"])
        ymin = "%.*f" % (p.coords_decimals, p["options"]["ymin"])
        ymax = "%.*f" % (p.coords_decimals, p["options"]["ymax"])

        if str(p["options"]["type"]) == "Geometry":
            gcode += "(TOOL DIAMETER: " + str(p["options"]["tool_dia"]) + units + ")\n"
            gcode += "(Feedrate_XY: " + str(p["feedrate"]) + units + "/min" + ")\n"
            gcode += "(Feedrate_Z: " + str(p["z_feedrate"]) + units + "/min" + ")\n"
            gcode += "(Feedrate rapids " + str(p["feedrate_rapid"]) + units + "/min" + ")\n" + "\n"
            gcode += "(Z_Cut: " + str(p["z_cut"]) + units + ")\n"
            if p["multidepth"] is True:
                gcode += (
                    "(DepthPerCut: "
                    + str(p["z_depthpercut"])
                    + units
                    + " <=>"
                    + str(math.ceil(abs(p["z_cut"]) / p["z_depthpercut"]))
                    + " passes"
                    + ")\n"
                )
            gcode += "(Z_Move: " + str(p["z_move"]) + units + ")\n"

        elif str(p["options"]["type"]) == "Excellon" and p["use_ui"] is True:
            gcode += "\n(TOOLS DIAMETER: )\n"
            for tool, val in p["exc_tools"].items():
                gcode += "(Tool: %s -> " % str(tool) + "Dia: %s" % str(val["tooldia"]) + ")\n"

            gcode += "\n(FEEDRATE Z: )\n"
            for tool, val in p["exc_tools"].items():
                gcode += (
                    "(Tool: %s -> " % str(tool)
                    + "Feedrate: %s" % str(val["data"]["tools_drill_feedrate_z"])
                    + ")\n"
                )

            gcode += "\n(FEEDRATE RAPIDS: )\n"
            for tool, val in p["exc_tools"].items():
                gcode += (
                    "(Tool: %s -> " % str(tool)
                    + "Feedrate Rapids: %s" % str(val["data"]["tools_drill_feedrate_rapid"])
                    + ")\n"
                )

            gcode += "\n(Z_CUT: )\n"
            for tool, val in p["exc_tools"].items():
                gcode += (
                    "(Tool: %s -> " % str(tool)
                    + "Z_Cut: %s" % str(val["data"]["tools_drill_cutz"])
                    + ")\n"
                )

            gcode += "\n(Tools Offset: )\n"
            for tool, val in p["exc_cnc_tools"].items():
                gcode += (
                    "(Tool: %s -> " % str(val["tool"])
                    + "Offset Z: %s" % str(val["data"]["tools_drill_offset"])
                    + ")\n"
                )

            if p["multidepth"] is True:
                gcode += "\n(DEPTH_PER_CUT: )\n"
                for tool, val in p["exc_tools"].items():
                    gcode += (
                        "(Tool: %s -> " % str(tool)
                        + "DeptPerCut: %s" % str(val["data"]["tools_drill_depthperpass"])
                        + ")\n"
                    )

            gcode += "\n(Z_MOVE: )\n"
            for tool, val in p["exc_tools"].items():
                gcode += (
                    "(Tool: %s -> " % str(tool)
                    + "Z_Move: %s" % str(val["data"]["tools_drill_travelz"])
                    + ")\n"
                )
            gcode += "\n"

        if p["toolchange"] is True:
            gcode += "(Z Toolchange: " + str(p["z_toolchange"]) + units + ")\n"

            if coords_xy is not None:
                gcode += (
                    "(X,Y Toolchange: "
                    + "%.*f, %.*f" % (p.decimals, coords_xy[0], p.decimals, coords_xy[1])
                    + units
                    + ")\n"
                )
            else:
                gcode += "(X,Y Toolchange: " + "None" + units + ")\n"

        gcode += "(Z Start: " + str(p["startz"]) + units + ")\n"
        gcode += "(Z End: " + str(p["z_end"]) + units + ")\n"
        if end_coords_xy is not None:
            gcode += (
                "(X,Y End: "
                + "%.*f, %.*f" % (p.decimals, end_coords_xy[0], p.decimals, end_coords_xy[1])
                + units
                + ")\n"
            )
        else:
            gcode += "(X,Y End: " + "None" + units + ")\n"
        gcode += "(Steps per circle: " + str(p["steps_per_circle"]) + ")\n"
        gcode += "(Steps per circle: " + str(p["steps_per_circle"]) + ")\n"

        if (
            str(p["options"]["type"]) == "Excellon"
            or str(p["options"]["type"]) == "Excellon Geometry"
        ):
            gcode += "(Preprocessor Excellon: " + str(p["pp_excellon_name"]) + ")\n" + "\n"
        else:
            gcode += "(Preprocessor Geometry: " + str(p["pp_geometry_name"]) + ")\n" + "\n"

        gcode += (
            "(X range: "
            + "{: >9s}".format(xmin)
            + " ... "
            + "{: >9s}".format(xmax)
            + " "
            + units
            + ")\n"
        )
        gcode += (
            "(Y range: "
            + "{: >9s}".format(ymin)
            + " ... "
            + "{: >9s}".format(ymax)
            + " "
            + units
            + ")\n\n"
        )

        gcode += "(Spindle Speed: %s RPM)\n" % str(p["spindlespeed"])

        gcode += "G20\n" if p.units.upper() == "IN" else "G21\n"
        gcode += "G90\n"
        gcode += "G94\n"

        return gcode

    def startz_code(self, p):
        if p.startz is not None:
            g = (
                "G00 "
                + "X"
                + self.coordinate_format % (p.coords_decimals, p.x)
                + " Y"
                + self.coordinate_format % (p.coords_decimals, p.y)
                + " Z"
                + self.coordinate_format % (p.coords_decimals, p.startz)
            )
            return g
        else:
            return ""

    def lift_code(self, p):
        g = (
            "G00 "
            + "X"
            + self.coordinate_format % (p.coords_decimals, p.x)
            + " Y"
            + self.coordinate_format % (p.coords_decimals, p.y)
            + " Z"
            + self.coordinate_format % (p.coords_decimals, p.z_move)
        )
        return g

    def down_code(self, p):
        g = (
            "G01 "
            + "X"
            + self.coordinate_format % (p.coords_decimals, p.x)
            + " Y"
            + self.coordinate_format % (p.coords_decimals, p.y)
            + " Z"
            + self.coordinate_format % (p.coords_decimals, p.z_cut)
        )
        return g

    def toolchange_code(self, p):
        z_toolchange = p.z_toolchange
        xy_toolchange = p.xy_toolchange
        f_plunge = p.f_plunge

        if xy_toolchange is not None:
            x_toolchange = xy_toolchange[0]
            y_toolchange = xy_toolchange[1]
        else:
            if str(p["options"]["type"]) == "Excellon":
                x_toolchange = p.oldx
                y_toolchange = p.oldy
            else:
                x_toolchange = p.x
                y_toolchange = p.y

        no_drills = 1

        if int(p.tool) == 1 and p.startz is not None:
            z_toolchange = p.startz

        toolC_formatted = "%.*f" % (p.decimals, p.toolC)

        if str(p["options"]["type"]) == "Excellon":
            for i in p["options"]["Tools_in_use"]:
                if i[0] == p.tool:
                    no_drills = i[2]
            gcode = """
M5      
G00 X{x_toolchange} Y{x_toolchange} Z{z_toolchange}
T{tool}
M6
(MSG, Change to Tool Dia = {toolC} ||| Total drills for tool T{tool} = {t_drills})
M0""".format(
                x_toolchange=self.coordinate_format % (p.coords_decimals, x_toolchange),
                y_toolchange=self.coordinate_format % (p.coords_decimals, y_toolchange),
                z_toolchange=self.coordinate_format % (p.coords_decimals, z_toolchange),
                tool=int(p.tool),
                t_drills=no_drills,
                toolC=toolC_formatted,
            )

            if f_plunge is True:
                gcode += """\nG00 X{x_toolchange} Y{x_toolchange} Z{z_move}""".format(
                    x_toolchange=self.coordinate_format % (p.coords_decimals, x_toolchange),
                    y_toolchange=self.coordinate_format % (p.coords_decimals, y_toolchange),
                    z_move=self.coordinate_format % (p.coords_decimals, p.z_move),
                )
            return gcode
        else:
            gcode = """
M5
G00 X{x_toolchange} Y{x_toolchange} Z{z_toolchange}
T{tool}
M6    
(MSG, Change to Tool Dia = {toolC})
M0""".format(
                x_toolchange=self.coordinate_format % (p.coords_decimals, x_toolchange),
                y_toolchange=self.coordinate_format % (p.coords_decimals, y_toolchange),
                z_toolchange=self.coordinate_format % (p.coords_decimals, z_toolchange),
                tool=int(p.tool),
                toolC=toolC_formatted,
            )

            if f_plunge is True:
                gcode += """\nG00 X{x_toolchange} Y{x_toolchange} Z{z_move}""".format(
                    x_toolchange=self.coordinate_format % (p.coords_decimals, x_toolchange),
                    y_toolchange=self.coordinate_format % (p.coords_decimals, y_toolchange),
                    z_move=self.coordinate_format % (p.coords_decimals, p.z_move),
                )
            return gcode

    def up_to_zero_code(self, p):
        g = (
            "G01 "
            + "X"
            + self.coordinate_format % (p.coords_decimals, p.x)
            + " Y"
            + self.coordinate_format % (p.coords_decimals, p.y)
            + " Z0"
        )
        return g

    def position_code(self, p):
        return ("X" + self.coordinate_format + " Y" + self.coordinate_format) % (
            p.coords_decimals,
            p.x,
            p.coords_decimals,
            p.y,
        )

    def rapid_code(self, p):
        g = ("G00 " + self.position_code(p)).format(**p)
        g += " Z" + self.coordinate_format % (p.coords_decimals, p.z_move)
        return g

    def linear_code(self, p):
        g = ("G01 " + self.position_code(p)).format(**p)
        g += " Z" + self.coordinate_format % (p.coords_decimals, p.z_cut)
        return g

    def end_code(self, p):
        coords_xy = p["xy_end"]
        if coords_xy and coords_xy != "":
            g = "G00 X{x} Y{y}".format(x=coords_xy[0], y=coords_xy[1]) + "\n"
        else:
            g = ("G00 " + self.position_code(p)).format(**p)
        g += " Z" + self.coordinate_format % (p.coords_decimals, p.z_end)
        return g

    def feedrate_code(self, p):
        return "G01 F" + str(self.feedrate_format % (p.fr_decimals, p.feedrate))

    def z_feedrate_code(self, p):
        return "G01 F" + str(self.feedrate_format % (p.fr_decimals, p.z_feedrate))

    def spindle_code(self, p):
        sdir = {"CW": "M03", "CCW": "M04"}[p.spindledir]
        if p.spindlespeed:
            return "%s S%s" % (sdir, str(p.spindlespeed))
        else:
            return sdir

    def dwell_code(self, p):
        if p.dwelltime:
            return "G4 P" + str(p.dwelltime)

    def spindle_stop_code(self, p):
        return "M05"
