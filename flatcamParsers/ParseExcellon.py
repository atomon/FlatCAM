# ########################################################## ##
# FlatCAM: 2D Post-processing for Manufacturing               #
# http://flatcam.org                                          #
# Author: Juan Pablo Caram (c)                                #
# Date: 2/5/2014                                              #
# MIT Licence                                                 #
# ########################################################## ##

from camlib import Geometry
import FlatCAMApp

import shapely.affinity as affinity
from shapely.geometry import Point, LineString
import numpy as np

import re
import logging
import traceback
from copy import deepcopy

import FlatCAMTranslation as fcTranslate

import gettext
import builtins

if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class Excellon(Geometry):
    """
    Here it is done all the Excellon parsing.

    *ATTRIBUTES*

    * ``tools`` (dict): The key is the tool name and the value is
      a dictionary specifying the tool:

    ================  ====================================
    Key               Value
    ================  ====================================
    C                 Diameter of the tool
    solid_geometry    Geometry list for each tool
    Others            Not supported (Ignored).
    ================  ====================================

    * ``drills`` (list): Each is a dictionary:

    ================  ====================================
    Key               Value
    ================  ====================================
    point             (Shapely.Point) Where to drill
    tool              (str) A key in ``tools``
    ================  ====================================

    * ``slots`` (list): Each is a dictionary

    ================  ====================================
    Key               Value
    ================  ====================================
    start             (Shapely.Point) Start point of the slot
    stop              (Shapely.Point) Stop point of the slot
    tool              (str) A key in ``tools``
    ================  ====================================
    """

    defaults = {
        "zeros": "L",
        "excellon_format_upper_mm": '3',
        "excellon_format_lower_mm": '3',
        "excellon_format_upper_in": '2',
        "excellon_format_lower_in": '4',
        "excellon_units": 'INCH',
        "geo_steps_per_circle": '64'
    }

    def __init__(self, zeros=None, excellon_format_upper_mm=None, excellon_format_lower_mm=None,
                 excellon_format_upper_in=None, excellon_format_lower_in=None, excellon_units=None,
                 geo_steps_per_circle=None):
        """
        The constructor takes no parameters.

        :return: Excellon object.
        :rtype: Excellon
        """
        self.decimals = self.app.decimals

        if geo_steps_per_circle is None:
            geo_steps_per_circle = int(Excellon.defaults['geo_steps_per_circle'])
        self.geo_steps_per_circle = int(geo_steps_per_circle)

        Geometry.__init__(self, geo_steps_per_circle=int(geo_steps_per_circle))

        # dictionary to store tools, see above for description
        self.tools = dict()
        # list to store the drills, see above for description
        self.drills = list()
        # self.slots (list) to store the slots; each is a dictionary
        self.slots = list()

        self.source_file = ''

        # it serve to flag if a start routing or a stop routing was encountered
        # if a stop is encounter and this flag is still 0 (so there is no stop for a previous start) issue error
        self.routing_flag = 1

        self.match_routing_start = None
        self.match_routing_stop = None

        self.num_tools = list()  # List for keeping the tools sorted
        self.index_per_tool = dict()  # Dictionary to store the indexed points for each tool

        # ## IN|MM -> Units are inherited from Geometry
        self.units = self.app.defaults['units']

        # Trailing "T" or leading "L" (default)
        # self.zeros = "T"
        self.zeros = zeros or self.defaults["zeros"]
        self.zeros_found = deepcopy(self.zeros)
        self.units_found = deepcopy(self.units)

        # this will serve as a default if the Excellon file has no info regarding of tool diameters (this info may be
        # in another file like for PCB WIzard ECAD software
        self.toolless_diam = 1.0
        # signal that the Excellon file has no tool diameter informations and the tools have bogus (random) diameter
        self.diameterless = False

        # Excellon format
        self.excellon_format_upper_in = excellon_format_upper_in or self.defaults["excellon_format_upper_in"]
        self.excellon_format_lower_in = excellon_format_lower_in or self.defaults["excellon_format_lower_in"]
        self.excellon_format_upper_mm = excellon_format_upper_mm or self.defaults["excellon_format_upper_mm"]
        self.excellon_format_lower_mm = excellon_format_lower_mm or self.defaults["excellon_format_lower_mm"]
        self.excellon_units = excellon_units or self.defaults["excellon_units"]
        # detected Excellon format is stored here:
        self.excellon_format = None

        # Attributes to be included in serialization
        # Always append to it because it carries contents
        # from Geometry.
        self.ser_attrs += ['tools', 'drills', 'zeros', 'excellon_format_upper_mm', 'excellon_format_lower_mm',
                           'excellon_format_upper_in', 'excellon_format_lower_in', 'excellon_units', 'slots',
                           'source_file']

        # ### Patterns ####
        # Regex basics:
        # ^ - beginning
        # $ - end
        # *: 0 or more, +: 1 or more, ?: 0 or 1

        # M48 - Beginning of Part Program Header
        self.hbegin_re = re.compile(r'^M48$')

        # ;HEADER - Beginning of Allegro Program Header
        self.allegro_hbegin_re = re.compile(r'\;\s*(HEADER)')

        # M95 or % - End of Part Program Header
        # NOTE: % has different meaning in the body
        self.hend_re = re.compile(r'^(?:M95|%)$')

        # FMAT Excellon format
        # Ignored in the parser
        # self.fmat_re = re.compile(r'^FMAT,([12])$')

        # Uunits and possible Excellon zeros and possible Excellon format
        # INCH uses 6 digits
        # METRIC uses 5/6
        self.units_re = re.compile(r'^(INCH|METRIC)(?:,([TL])Z)?,?(\d*\.\d+)?.*$')

        # Tool definition/parameters (?= is look-ahead
        # NOTE: This might be an overkill!
        # self.toolset_re = re.compile(r'^T(0?\d|\d\d)(?=.*C(\d*\.?\d*))?' +
        #                              r'(?=.*F(\d*\.?\d*))?(?=.*S(\d*\.?\d*))?' +
        #                              r'(?=.*B(\d*\.?\d*))?(?=.*H(\d*\.?\d*))?' +
        #                              r'(?=.*Z([-\+]?\d*\.?\d*))?[CFSBHT]')
        self.toolset_re = re.compile(r'^T(\d+)(?=.*C,?(\d*\.?\d*))?' +
                                     r'(?=.*F(\d*\.?\d*))?(?=.*S(\d*\.?\d*))?' +
                                     r'(?=.*B(\d*\.?\d*))?(?=.*H(\d*\.?\d*))?' +
                                     r'(?=.*Z([-\+]?\d*\.?\d*))?[CFSBHT]')

        self.detect_gcode_re = re.compile(r'^G2([01])$')

        # Tool select
        # Can have additional data after tool number but
        # is ignored if present in the header.
        # Warning: This will match toolset_re too.
        # self.toolsel_re = re.compile(r'^T((?:\d\d)|(?:\d))')
        self.toolsel_re = re.compile(r'^T(\d+)')

        # Headerless toolset
        # self.toolset_hl_re = re.compile(r'^T(\d+)(?=.*C(\d*\.?\d*))')
        self.toolset_hl_re = re.compile(r'^T(\d+)(?:.?C(\d+\.?\d*))?')

        # Comment
        self.comm_re = re.compile(r'^;(.*)$')

        # Absolute/Incremental G90/G91
        self.absinc_re = re.compile(r'^G9([01])$')

        # Modes of operation
        # 1-linear, 2-circCW, 3-cirCCW, 4-vardwell, 5-Drill
        self.modes_re = re.compile(r'^G0([012345])')

        # Measuring mode
        # 1-metric, 2-inch
        self.meas_re = re.compile(r'^M7([12])$')

        # Coordinates
        # self.xcoord_re = re.compile(r'^X(\d*\.?\d*)(?:Y\d*\.?\d*)?$')
        # self.ycoord_re = re.compile(r'^(?:X\d*\.?\d*)?Y(\d*\.?\d*)$')
        coordsperiod_re_string = r'(?=.*X([-\+]?\d*\.\d*))?(?=.*Y([-\+]?\d*\.\d*))?[XY]'
        self.coordsperiod_re = re.compile(coordsperiod_re_string)

        coordsnoperiod_re_string = r'(?!.*\.)(?=.*X([-\+]?\d*))?(?=.*Y([-\+]?\d*))?[XY]'
        self.coordsnoperiod_re = re.compile(coordsnoperiod_re_string)

        # Slots parsing
        slots_re_string = r'^([^G]+)G85(.*)$'
        self.slots_re = re.compile(slots_re_string)

        # R - Repeat hole (# times, X offset, Y offset)
        self.rep_re = re.compile(r'^R(\d+)(?=.*[XY])+(?:X([-\+]?\d*\.?\d*))?(?:Y([-\+]?\d*\.?\d*))?$')

        # Various stop/pause commands
        self.stop_re = re.compile(r'^((G04)|(M09)|(M06)|(M00)|(M30))')

        # Allegro Excellon format support
        self.tool_units_re = re.compile(r'(\;\s*Holesize \d+.\s*\=\s*(\d+.\d+).*(MILS|MM))')

        # Altium Excellon format support
        # it's a comment like this: ";FILE_FORMAT=2:5"
        self.altium_format = re.compile(r'^;\s*(?:FILE_FORMAT)?(?:Format)?[=|:]\s*(\d+)[:|.](\d+).*$')

        # Parse coordinates
        self.leadingzeros_re = re.compile(r'^[-\+]?(0*)(\d*)')

        # Repeating command
        self.repeat_re = re.compile(r'R(\d+)')

    def parse_file(self, filename=None, file_obj=None):
        """
        Reads the specified file as array of lines as
        passes it to ``parse_lines()``.

        :param filename: The file to be read and parsed.
        :type filename: str
        :return: None
        """
        if file_obj:
            estr = file_obj
        else:
            if filename is None:
                return "fail"
            efile = open(filename, 'r')
            estr = efile.readlines()
            efile.close()

        try:
            self.parse_lines(estr)
        except Exception:
            return "fail"

    def parse_lines(self, elines):
        """
        Main Excellon parser.

        :param elines: List of strings, each being a line of Excellon code.
        :type elines: list
        :return: None
        """

        # State variables
        current_tool = ""
        in_header = False
        headerless = False
        current_x = None
        current_y = None

        slot_current_x = None
        slot_current_y = None

        name_tool = 0
        allegro_warning = False
        line_units_found = False

        repeating_x = 0
        repeating_y = 0
        repeat = 0

        line_units = ''

        # ## Parsing starts here ## ##
        line_num = 0  # Line number
        eline = ""
        try:
            for eline in elines:
                if self.app.abort_flag:
                    # graceful abort requested by the user
                    raise FlatCAMApp.GracefulException

                line_num += 1
                # log.debug("%3d %s" % (line_num, str(eline)))

                self.source_file += eline

                # Cleanup lines
                eline = eline.strip(' \r\n')

                # Excellon files and Gcode share some extensions therefore if we detect G20 or G21 it's GCODe
                # and we need to exit from here
                if self.detect_gcode_re.search(eline):
                    log.warning("This is GCODE mark: %s" % eline)
                    self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_('This is GCODE mark'), eline))
                    return

                # Header Begin (M48) #
                if self.hbegin_re.search(eline):
                    in_header = True
                    headerless = False
                    log.warning("Found start of the header: %s" % eline)
                    continue

                # Allegro Header Begin (;HEADER) #
                if self.allegro_hbegin_re.search(eline):
                    in_header = True
                    allegro_warning = True
                    log.warning("Found ALLEGRO start of the header: %s" % eline)
                    continue

                # Search for Header End #
                # Since there might be comments in the header that include header end char (% or M95)
                # we ignore the lines starting with ';' that contains such header end chars because it is not a
                # real header end.
                if self.comm_re.search(eline):
                    match = self.tool_units_re.search(eline)
                    if match:
                        if line_units_found is False:
                            line_units_found = True
                            line_units = match.group(3)
                            self.convert_units({"MILS": "IN", "MM": "MM"}[line_units])
                            log.warning("Type of Allegro UNITS found inline in comments: %s" % line_units)

                        if match.group(2):
                            name_tool += 1
                            if line_units == 'MILS':
                                spec = {"C": (float(match.group(2)) / 1000)}
                                self.tools[str(name_tool)] = spec
                                log.debug("Tool definition: %s %s" % (name_tool, spec))
                            else:
                                spec = {"C": float(match.group(2))}
                                self.tools[str(name_tool)] = spec
                                log.debug("Tool definition: %s %s" % (name_tool, spec))
                            spec['solid_geometry'] = []
                            continue
                    # search for Altium Excellon Format / Sprint Layout who is included as a comment
                    match = self.altium_format.search(eline)
                    if match:
                        self.excellon_format_upper_mm = match.group(1)
                        self.excellon_format_lower_mm = match.group(2)

                        self.excellon_format_upper_in = match.group(1)
                        self.excellon_format_lower_in = match.group(2)
                        log.warning("Altium Excellon format preset found in comments: %s:%s" %
                                    (match.group(1), match.group(2)))
                        continue
                    else:
                        log.warning("Line ignored, it's a comment: %s" % eline)
                else:
                    if self.hend_re.search(eline):
                        if in_header is False or bool(self.tools) is False:
                            log.warning("Found end of the header but there is no header: %s" % eline)
                            log.warning("The only useful data in header are tools, units and format.")
                            log.warning("Therefore we will create units and format based on defaults.")
                            headerless = True
                            try:
                                self.convert_units({"INCH": "IN", "METRIC": "MM"}[self.excellon_units])
                            except Exception as e:
                                log.warning("Units could not be converted: %s" % str(e))

                        in_header = False
                        # for Allegro type of Excellons we reset name_tool variable so we can reuse it for toolchange
                        if allegro_warning is True:
                            name_tool = 0
                        log.warning("Found end of the header: %s" % eline)
                        continue

                # ## Alternative units format M71/M72
                # Supposed to be just in the body (yes, the body)
                # but some put it in the header (PADS for example).
                # Will detect anywhere. Occurrence will change the
                # object's units.
                match = self.meas_re.match(eline)
                if match:
                    self.units = {"1": "MM", "2": "IN"}[match.group(1)]

                    # Modified for issue #80
                    log.debug("ALternative M71/M72 units found, before conversion: %s" % self.units)
                    self.convert_units(self.units)
                    log.debug("ALternative M71/M72 units found, after conversion: %s" % self.units)
                    if self.units == 'MM':
                        log.warning("Excellon format preset is: %s:%s" %
                                    (str(self.excellon_format_upper_mm), str(self.excellon_format_lower_mm)))
                    else:
                        log.warning("Excellon format preset is: %s:%s" %
                                    (str(self.excellon_format_upper_in), str(self.excellon_format_lower_in)))
                    continue

                # ### Body ####
                if not in_header:

                    # ## Tool change ###
                    match = self.toolsel_re.search(eline)
                    if match:
                        current_tool = str(int(match.group(1)))
                        log.debug("Tool change: %s" % current_tool)
                        if bool(headerless):
                            match = self.toolset_hl_re.search(eline)
                            if match:
                                name = str(int(match.group(1)))
                                try:
                                    diam = float(match.group(2))
                                except Exception:
                                    # it's possible that tool definition has only tool number and no diameter info
                                    # (those could be in another file like PCB Wizard do)
                                    # then match.group(2) = None and float(None) will create the exception
                                    # the bellow construction is so each tool will have a slightly different diameter
                                    # starting with a default value, to allow Excellon editing after that
                                    self.diameterless = True
                                    self.app.inform.emit('[WARNING] %s%s %s' %
                                                         (_("No tool diameter info's. See shell.\n"
                                                            "A tool change event: T"),
                                                          str(current_tool),
                                                          _("was found but the Excellon file "
                                                            "have no informations regarding the tool "
                                                            "diameters therefore the application will try to load it "
                                                            "by using some 'fake' diameters.\n"
                                                            "The user needs to edit the resulting Excellon object and "
                                                            "change the diameters to reflect the real diameters.")
                                                          )
                                                         )

                                    if self.excellon_units == 'MM':
                                        diam = self.toolless_diam + (int(current_tool) - 1) / 100
                                    else:
                                        diam = (self.toolless_diam + (int(current_tool) - 1) / 100) / 25.4

                                spec = {"C": diam, 'solid_geometry': []}
                                self.tools[name] = spec
                                log.debug("Tool definition out of header: %s %s" % (name, spec))

                        continue

                    # ## Allegro Type Tool change ###
                    if allegro_warning is True:
                        match = self.absinc_re.search(eline)
                        match1 = self.stop_re.search(eline)
                        if match or match1:
                            name_tool += 1
                            current_tool = str(name_tool)
                            log.debug("Tool change for Allegro type of Excellon: %s" % current_tool)
                            continue

                    # ## Slots parsing for drilled slots (contain G85)
                    # a Excellon drilled slot line may look like this:
                    # X01125Y0022244G85Y0027756
                    match = self.slots_re.search(eline)
                    if match:
                        # signal that there are milling slots operations
                        self.defaults['excellon_drills'] = False

                        # the slot start coordinates group is to the left of G85 command (group(1) )
                        # the slot stop coordinates group is to the right of G85 command (group(2) )
                        start_coords_match = match.group(1)
                        stop_coords_match = match.group(2)

                        # Slot coordinates without period # ##
                        # get the coordinates for slot start and for slot stop into variables
                        start_coords_noperiod = self.coordsnoperiod_re.search(start_coords_match)
                        stop_coords_noperiod = self.coordsnoperiod_re.search(stop_coords_match)
                        if start_coords_noperiod:
                            try:
                                slot_start_x = self.parse_number(start_coords_noperiod.group(1))
                                slot_current_x = slot_start_x
                            except TypeError:
                                slot_start_x = slot_current_x
                            except Exception:
                                return

                            try:
                                slot_start_y = self.parse_number(start_coords_noperiod.group(2))
                                slot_current_y = slot_start_y
                            except TypeError:
                                slot_start_y = slot_current_y
                            except Exception:
                                return

                            try:
                                slot_stop_x = self.parse_number(stop_coords_noperiod.group(1))
                                slot_current_x = slot_stop_x
                            except TypeError:
                                slot_stop_x = slot_current_x
                            except Exception:
                                return

                            try:
                                slot_stop_y = self.parse_number(stop_coords_noperiod.group(2))
                                slot_current_y = slot_stop_y
                            except TypeError:
                                slot_stop_y = slot_current_y
                            except Exception:
                                return

                            if (slot_start_x is None or slot_start_y is None or
                                    slot_stop_x is None or slot_stop_y is None):
                                log.error("Slots are missing some or all coordinates.")
                                continue

                            # we have a slot
                            log.debug('Parsed a slot with coordinates: ' + str([slot_start_x,
                                                                                slot_start_y, slot_stop_x,
                                                                                slot_stop_y]))

                            # store current tool diameter as slot diameter
                            slot_dia = 0.05
                            try:
                                slot_dia = float(self.tools[current_tool]['C'])
                            except Exception as e:
                                pass
                            log.debug(
                                'Milling/Drilling slot with tool %s, diam=%f' % (
                                    current_tool,
                                    slot_dia
                                )
                            )

                            self.slots.append(
                                {
                                    'start': Point(slot_start_x, slot_start_y),
                                    'stop': Point(slot_stop_x, slot_stop_y),
                                    'tool': current_tool
                                }
                            )
                            continue

                        # Slot coordinates with period: Use literally. ###
                        # get the coordinates for slot start and for slot stop into variables
                        start_coords_period = self.coordsperiod_re.search(start_coords_match)
                        stop_coords_period = self.coordsperiod_re.search(stop_coords_match)
                        if start_coords_period:

                            try:
                                slot_start_x = float(start_coords_period.group(1))
                                slot_current_x = slot_start_x
                            except TypeError:
                                slot_start_x = slot_current_x
                            except Exception:
                                return

                            try:
                                slot_start_y = float(start_coords_period.group(2))
                                slot_current_y = slot_start_y
                            except TypeError:
                                slot_start_y = slot_current_y
                            except Exception:
                                return

                            try:
                                slot_stop_x = float(stop_coords_period.group(1))
                                slot_current_x = slot_stop_x
                            except TypeError:
                                slot_stop_x = slot_current_x
                            except Exception:
                                return

                            try:
                                slot_stop_y = float(stop_coords_period.group(2))
                                slot_current_y = slot_stop_y
                            except TypeError:
                                slot_stop_y = slot_current_y
                            except Exception:
                                return

                            if (slot_start_x is None or slot_start_y is None or
                                    slot_stop_x is None or slot_stop_y is None):
                                log.error("Slots are missing some or all coordinates.")
                                continue

                            # we have a slot
                            log.debug('Parsed a slot with coordinates: ' + str([slot_start_x,
                                                                                slot_start_y, slot_stop_x,
                                                                                slot_stop_y]))

                            # store current tool diameter as slot diameter
                            slot_dia = 0.05
                            try:
                                slot_dia = float(self.tools[current_tool]['C'])
                            except Exception as e:
                                pass
                            log.debug(
                                'Milling/Drilling slot with tool %s, diam=%f' % (
                                    current_tool,
                                    slot_dia
                                )
                            )

                            self.slots.append(
                                {
                                    'start': Point(slot_start_x, slot_start_y),
                                    'stop': Point(slot_stop_x, slot_stop_y),
                                    'tool': current_tool
                                }
                            )
                        continue

                    # ## Coordinates without period # ##
                    match = self.coordsnoperiod_re.search(eline)
                    if match:
                        matchr = self.repeat_re.search(eline)
                        if matchr:
                            repeat = int(matchr.group(1))

                        try:
                            x = self.parse_number(match.group(1))
                            repeating_x = current_x
                            current_x = x
                        except TypeError:
                            x = current_x
                            repeating_x = 0
                        except Exception:
                            return

                        try:
                            y = self.parse_number(match.group(2))
                            repeating_y = current_y
                            current_y = y
                        except TypeError:
                            y = current_y
                            repeating_y = 0
                        except Exception:
                            return

                        if x is None or y is None:
                            log.error("Missing coordinates")
                            continue

                        # ## Excellon Routing parse
                        if len(re.findall("G00", eline)) > 0:
                            self.match_routing_start = 'G00'

                            # signal that there are milling slots operations
                            self.defaults['excellon_drills'] = False

                            self.routing_flag = 0
                            slot_start_x = x
                            slot_start_y = y
                            continue

                        if self.routing_flag == 0:
                            if len(re.findall("G01", eline)) > 0:
                                self.match_routing_stop = 'G01'

                                # signal that there are milling slots operations
                                self.defaults['excellon_drills'] = False

                                self.routing_flag = 1
                                slot_stop_x = x
                                slot_stop_y = y
                                self.slots.append(
                                    {
                                        'start': Point(slot_start_x, slot_start_y),
                                        'stop': Point(slot_stop_x, slot_stop_y),
                                        'tool': current_tool
                                    }
                                )
                                continue

                        if self.match_routing_start is None and self.match_routing_stop is None:
                            if repeat == 0:
                                # signal that there are drill operations
                                self.defaults['excellon_drills'] = True
                                self.drills.append({'point': Point((x, y)), 'tool': current_tool})
                            else:
                                coordx = x
                                coordy = y
                                while repeat > 0:
                                    if repeating_x:
                                        coordx = (repeat * x) + repeating_x
                                    if repeating_y:
                                        coordy = (repeat * y) + repeating_y
                                    self.drills.append({'point': Point((coordx, coordy)), 'tool': current_tool})
                                    repeat -= 1
                            repeating_x = repeating_y = 0
                            # log.debug("{:15} {:8} {:8}".format(eline, x, y))
                            continue

                    # ## Coordinates with period: Use literally. # ##
                    match = self.coordsperiod_re.search(eline)
                    if match:
                        matchr = self.repeat_re.search(eline)
                        if matchr:
                            repeat = int(matchr.group(1))

                    if match:
                        # signal that there are drill operations
                        self.defaults['excellon_drills'] = True
                        try:
                            x = float(match.group(1))
                            repeating_x = current_x
                            current_x = x
                        except TypeError:
                            x = current_x
                            repeating_x = 0

                        try:
                            y = float(match.group(2))
                            repeating_y = current_y
                            current_y = y
                        except TypeError:
                            y = current_y
                            repeating_y = 0

                        if x is None or y is None:
                            log.error("Missing coordinates")
                            continue

                        # ## Excellon Routing parse
                        if len(re.findall("G00", eline)) > 0:
                            self.match_routing_start = 'G00'

                            # signal that there are milling slots operations
                            self.defaults['excellon_drills'] = False

                            self.routing_flag = 0
                            slot_start_x = x
                            slot_start_y = y
                            continue

                        if self.routing_flag == 0:
                            if len(re.findall("G01", eline)) > 0:
                                self.match_routing_stop = 'G01'

                                # signal that there are milling slots operations
                                self.defaults['excellon_drills'] = False

                                self.routing_flag = 1
                                slot_stop_x = x
                                slot_stop_y = y
                                self.slots.append(
                                    {
                                        'start': Point(slot_start_x, slot_start_y),
                                        'stop': Point(slot_stop_x, slot_stop_y),
                                        'tool': current_tool
                                    }
                                )
                                continue

                        if self.match_routing_start is None and self.match_routing_stop is None:
                            # signal that there are drill operations
                            if repeat == 0:
                                # signal that there are drill operations
                                self.defaults['excellon_drills'] = True
                                self.drills.append({'point': Point((x, y)), 'tool': current_tool})
                            else:
                                coordx = x
                                coordy = y
                                while repeat > 0:
                                    if repeating_x:
                                        coordx = (repeat * x) + repeating_x
                                    if repeating_y:
                                        coordy = (repeat * y) + repeating_y
                                    self.drills.append({'point': Point((coordx, coordy)), 'tool': current_tool})
                                    repeat -= 1
                            repeating_x = repeating_y = 0
                            # log.debug("{:15} {:8} {:8}".format(eline, x, y))
                            continue

                # ### Header ####
                if in_header:

                    # ## Tool definitions # ##
                    match = self.toolset_re.search(eline)
                    if match:
                        name = str(int(match.group(1)))
                        spec = {"C": float(match.group(2)), 'solid_geometry': []}
                        self.tools[name] = spec
                        log.debug("Tool definition: %s %s" % (name, spec))
                        continue

                    # ## Units and number format # ##
                    match = self.units_re.match(eline)
                    if match:
                        self.units = {"METRIC": "MM", "INCH": "IN"}[match.group(1)]
                        self.zeros = match.group(2)  # "T" or "L". Might be empty
                        self.excellon_format = match.group(3)
                        if self.excellon_format:
                            upper = len(self.excellon_format.partition('.')[0])
                            lower = len(self.excellon_format.partition('.')[2])
                            if self.units == 'MM':
                                self.excellon_format_upper_mm = upper
                                self.excellon_format_lower_mm = lower
                            else:
                                self.excellon_format_upper_in = upper
                                self.excellon_format_lower_in = lower

                        # Modified for issue #80
                        log.warning("UNITS found inline before conversion: %s" % self.units)
                        self.convert_units(self.units)
                        log.warning("UNITS found inline after conversion: %s" % self.units)
                        if self.units == 'MM':
                            log.warning("Excellon format preset is: %s:%s" %
                                        (str(self.excellon_format_upper_mm), str(self.excellon_format_lower_mm)))
                        else:
                            log.warning("Excellon format preset is: %s:%s" %
                                        (str(self.excellon_format_upper_in), str(self.excellon_format_lower_in)))
                        log.warning("Type of ZEROS found inline, in header: %s" % self.zeros)
                        continue

                    # Search for units type again it might be alone on the line
                    if "INCH" in eline:
                        line_units = "IN"
                        # Modified for issue #80
                        log.warning("Type of UNITS found inline, in header, before conversion: %s" % line_units)
                        self.convert_units(line_units)
                        log.warning("Type of UNITS found inline, in header, after conversion: %s" % self.units)
                        log.warning("Excellon format preset is: %s:%s" %
                                    (str(self.excellon_format_upper_in), str(self.excellon_format_lower_in)))
                        continue
                    elif "METRIC" in eline:
                        line_units = "MM"
                        # Modified for issue #80
                        log.warning("Type of UNITS found inline, in header, before conversion: %s" % line_units)
                        self.convert_units(line_units)
                        log.warning("Type of UNITS found inline, in header, after conversion: %s" % self.units)
                        log.warning("Excellon format preset is: %s:%s" %
                                    (str(self.excellon_format_upper_mm), str(self.excellon_format_lower_mm)))
                        continue

                    # Search for zeros type again because it might be alone on the line
                    match = re.search(r'[LT]Z', eline)
                    if match:
                        self.zeros = match.group()
                        log.warning("Type of ZEROS found: %s" % self.zeros)
                        continue

                # ## Units and number format outside header# ##
                match = self.units_re.match(eline)
                if match:
                    self.units = self.units = {"METRIC": "MM", "INCH": "IN"}[match.group(1)]
                    self.zeros = match.group(2)  # "T" or "L". Might be empty
                    self.excellon_format = match.group(3)
                    if self.excellon_format:
                        upper = len(self.excellon_format.partition('.')[0])
                        lower = len(self.excellon_format.partition('.')[2])
                        if self.units == 'MM':
                            self.excellon_format_upper_mm = upper
                            self.excellon_format_lower_mm = lower
                        else:
                            self.excellon_format_upper_in = upper
                            self.excellon_format_lower_in = lower

                    # Modified for issue #80
                    log.warning("Type of UNITS found outside header, inline before conversion: %s" % self.units)
                    self.convert_units(self.units)
                    log.warning("Type of UNITS found outside header, inline after conversion: %s" % self.units)

                    if self.units == 'MM':
                        log.warning("Excellon format preset is: %s:%s" %
                                    (str(self.excellon_format_upper_mm), str(self.excellon_format_lower_mm)))
                    else:
                        log.warning("Excellon format preset is: %s:%s" %
                                    (str(self.excellon_format_upper_in), str(self.excellon_format_lower_in)))
                    log.warning("Type of ZEROS found outside header, inline: %s" % self.zeros)
                    continue

                log.warning("Line ignored: %s" % eline)

            # make sure that since we are in headerless mode, we convert the tools only after the file parsing
            # is finished since the tools definitions are spread in the Excellon body. We use as units the value
            # from self.defaults['excellon_units']

            log.info("Zeros: %s, Units %s." % (self.zeros, self.units))
        except Exception:
            log.error("Excellon PARSING FAILED. Line %d: %s" % (line_num, eline))
            msg = '[ERROR_NOTCL] %s' % \
                  _("An internal error has ocurred. See shell.\n")
            msg += ('{e_code} {tx} {l_nr}: {line}\n').format(
                e_code='[ERROR]',
                tx=_("Excellon Parser error.\nParsing Failed. Line"),
                l_nr=line_num,
                line=eline)
            msg += traceback.format_exc()
            self.app.inform.emit(msg)

            return "fail"

    def parse_number(self, number_str):
        """
        Parses coordinate numbers without period.

        :param number_str: String representing the numerical value.
        :type number_str: str
        :return: Floating point representation of the number
        :rtype: float
        """

        match = self.leadingzeros_re.search(number_str)
        nr_length = len(match.group(1)) + len(match.group(2))
        try:
            if self.zeros == "L" or self.zeros == "LZ":  # Leading
                # With leading zeros, when you type in a coordinate,
                # the leading zeros must always be included.  Trailing zeros
                # are unneeded and may be left off. The CNC-7 will automatically add them.
                # r'^[-\+]?(0*)(\d*)'
                # 6 digits are divided by 10^4
                # If less than size digits, they are automatically added,
                # 5 digits then are divided by 10^3 and so on.

                if self.units.lower() == "in":
                    result = float(number_str) / (10 ** (float(nr_length) - float(self.excellon_format_upper_in)))
                else:
                    result = float(number_str) / (10 ** (float(nr_length) - float(self.excellon_format_upper_mm)))
                return result
            else:  # Trailing
                # You must show all zeros to the right of the number and can omit
                # all zeros to the left of the number. The CNC-7 will count the number
                # of digits you typed and automatically fill in the missing zeros.
                # ## flatCAM expects 6digits
                # flatCAM expects the number of digits entered into the defaults

                if self.units.lower() == "in":  # Inches is 00.0000
                    result = float(number_str) / (10 ** (float(self.excellon_format_lower_in)))
                else:  # Metric is 000.000
                    result = float(number_str) / (10 ** (float(self.excellon_format_lower_mm)))
                return result
        except Exception as e:
            log.error("Aborted. Operation could not be completed due of %s" % str(e))
            return

    def create_geometry(self):
        """
        Creates circles of the tool diameter at every point
        specified in ``self.drills``. Also creates geometries (polygons)
        for the slots as specified in ``self.slots``
        All the resulting geometry is stored into self.solid_geometry list.
        The list self.solid_geometry has 2 elements: first is a dict with the drills geometry,
        and second element is another similar dict that contain the slots geometry.

        Each dict has as keys the tool diameters and as values lists with Shapely objects, the geometries
        ================  ====================================
        Key               Value
        ================  ====================================
        tool_diameter     list of (Shapely.Point) Where to drill
        ================  ====================================

        :return: None
        """

        log.debug("flatcamParsers.ParseExcellon.Excellon.create_geometry()")
        self.solid_geometry = []
        try:
            # clear the solid_geometry in self.tools
            for tool in self.tools:
                try:
                    self.tools[tool]['solid_geometry'][:] = []
                except KeyError:
                    self.tools[tool]['solid_geometry'] = []

            for drill in self.drills:
                # poly = drill['point'].buffer(self.tools[drill['tool']]["C"]/2.0)
                if drill['tool'] is '':
                    self.app.inform.emit('[WARNING] %s' %
                                         _("Excellon.create_geometry() -> a drill location was skipped "
                                           "due of not having a tool associated.\n"
                                           "Check the resulting GCode."))
                    log.debug("flatcamParsers.ParseExcellon.Excellon.create_geometry() -> a drill location was skipped "
                              "due of not having a tool associated")
                    continue
                tooldia = self.tools[drill['tool']]['C']
                poly = drill['point'].buffer(tooldia / 2.0, int(int(self.geo_steps_per_circle) / 4))
                self.solid_geometry.append(poly)
                self.tools[drill['tool']]['solid_geometry'].append(poly)

            for slot in self.slots:
                slot_tooldia = self.tools[slot['tool']]['C']
                start = slot['start']
                stop = slot['stop']

                lines_string = LineString([start, stop])
                poly = lines_string.buffer(slot_tooldia / 2.0, int(int(self.geo_steps_per_circle) / 4))
                self.solid_geometry.append(poly)
                self.tools[slot['tool']]['solid_geometry'].append(poly)

        except Exception as e:
            log.debug("flatcamParsers.ParseExcellon.Excellon.create_geometry() -> "
                      "Excellon geometry creation failed due of ERROR: %s" % str(e))
            return "fail"

    def bounds(self):
        """
        Returns coordinates of rectangular bounds
        of Excellon geometry: (xmin, ymin, xmax, ymax).
        """
        # fixed issue of getting bounds only for one level lists of objects
        # now it can get bounds for nested lists of objects

        log.debug("flatcamParsers.ParseExcellon.Excellon.bounds()")

        if self.solid_geometry is None or not self.tools:
            log.debug("flatcamParsers.ParseExcellon.Excellon -> solid_geometry is None")
            return 0, 0, 0, 0

        def bounds_rec(obj):
            if type(obj) is list:
                minx = np.Inf
                miny = np.Inf
                maxx = -np.Inf
                maxy = -np.Inf

                for k in obj:
                    if type(k) is dict:
                        for key in k:
                            minx_, miny_, maxx_, maxy_ = bounds_rec(k[key])
                            minx = min(minx, minx_)
                            miny = min(miny, miny_)
                            maxx = max(maxx, maxx_)
                            maxy = max(maxy, maxy_)
                    else:
                        minx_, miny_, maxx_, maxy_ = bounds_rec(k)
                        minx = min(minx, minx_)
                        miny = min(miny, miny_)
                        maxx = max(maxx, maxx_)
                        maxy = max(maxy, maxy_)
                return minx, miny, maxx, maxy
            else:
                # it's a Shapely object, return it's bounds
                return obj.bounds

        minx_list = []
        miny_list = []
        maxx_list = []
        maxy_list = []

        for tool in self.tools:
            minx, miny, maxx, maxy = bounds_rec(self.tools[tool]['solid_geometry'])
            minx_list.append(minx)
            miny_list.append(miny)
            maxx_list.append(maxx)
            maxy_list.append(maxy)

        return min(minx_list), min(miny_list), max(maxx_list), max(maxy_list)

    def convert_units(self, units):
        """
        This function first convert to the the units found in the Excellon file but it converts tools that
        are not there yet so it has no effect other than it signal that the units are the ones in the file.

        On object creation, in new_object(), true conversion is done because this is done at the end of the
        Excellon file parsing, the tools are inside and self.tools is really converted from the units found
        inside the file to the FlatCAM units.

        Kind of convolute way to make the conversion and it is based on the assumption that the Excellon file
        will have detected the units before the tools are parsed and stored in self.tools
        :param units:
        :type str: IN or MM
        :return:
        """

        # factor = Geometry.convert_units(self, units)
        obj_units = units
        if obj_units.upper() == self.units.upper():
            factor = 1.0
        elif obj_units.upper() == "MM":
            factor = 25.4
        elif obj_units.upper() == "IN":
            factor = 1 / 25.4
        else:
            log.error("Unsupported units: %s" % str(obj_units))
            factor = 1.0
        log.debug("flatcamParsers.ParseExcellon.Excellon.convert_units() --> Factor: %s" % str(factor))

        self.units = obj_units
        self.scale(factor, factor)
        self.file_units_factor = factor

        # Tools
        for tname in self.tools:
            self.tools[tname]["C"] *= factor

        self.create_geometry()
        return factor

    def scale(self, xfactor, yfactor=None, point=None):
        """
        Scales geometry on the XY plane in the object by a given factor.
        Tool sizes, feedrates an Z-plane dimensions are untouched.

        :param xfactor: Number by which to scale the object.
        :type xfactor: float
        :param yfactor: Number by which to scale the object.
        :type yfactor: float
        :return: None
        :rtype: NOne
        """
        log.debug("flatcamParsers.ParseExcellon.Excellon.scale()")

        if yfactor is None:
            yfactor = xfactor

        if point is None:
            px = 0
            py = 0
        else:
            px, py = point

        if xfactor == 0 and yfactor == 0:
            return

        def scale_geom(obj):
            if type(obj) is list:
                new_obj = []
                for g in obj:
                    new_obj.append(scale_geom(g))
                return new_obj
            else:
                try:
                    return affinity.scale(obj, xfactor, yfactor, origin=(px, py))
                except AttributeError:
                    return obj

        # variables to display the percentage of work done
        self.geo_len = 0
        try:
            for g in self.drills:
                self.geo_len += 1
        except TypeError:
            self.geo_len = 1
        self.old_disp_number = 0
        self.el_count = 0

        # Drills
        for drill in self.drills:
            drill['point'] = affinity.scale(drill['point'], xfactor, yfactor, origin=(px, py))

            self.el_count += 1
            disp_number = int(np.interp(self.el_count, [0, self.geo_len], [0, 100]))
            if self.old_disp_number < disp_number <= 100:
                self.app.proc_container.update_view_text(' %d%%' % disp_number)
                self.old_disp_number = disp_number

        # scale solid_geometry
        for tool in self.tools:
            self.tools[tool]['solid_geometry'] = scale_geom(self.tools[tool]['solid_geometry'])

        # Slots
        for slot in self.slots:
            slot['stop'] = affinity.scale(slot['stop'], xfactor, yfactor, origin=(px, py))
            slot['start'] = affinity.scale(slot['start'], xfactor, yfactor, origin=(px, py))

        self.create_geometry()
        self.app.proc_container.new_text = ''

    def offset(self, vect):
        """
        Offsets geometry on the XY plane in the object by a given vector.

        :param vect: (x, y) offset vector.
        :type vect: tuple
        :return: None
        """
        log.debug("flatcamParsers.ParseExcellon.Excellon.offset()")

        dx, dy = vect

        if dx == 0 and dy == 0:
            return

        def offset_geom(obj):
            if type(obj) is list:
                new_obj = []
                for g in obj:
                    new_obj.append(offset_geom(g))
                return new_obj
            else:
                try:
                    return affinity.translate(obj, xoff=dx, yoff=dy)
                except AttributeError:
                    return obj

        # variables to display the percentage of work done
        self.geo_len = 0
        try:
            for g in self.drills:
                self.geo_len += 1
        except TypeError:
            self.geo_len = 1
        self.old_disp_number = 0
        self.el_count = 0

        # Drills
        for drill in self.drills:
            drill['point'] = affinity.translate(drill['point'], xoff=dx, yoff=dy)

            self.el_count += 1
            disp_number = int(np.interp(self.el_count, [0, self.geo_len], [0, 100]))
            if self.old_disp_number < disp_number <= 100:
                self.app.proc_container.update_view_text(' %d%%' % disp_number)
                self.old_disp_number = disp_number

        # offset solid_geometry
        for tool in self.tools:
            self.tools[tool]['solid_geometry'] = offset_geom(self.tools[tool]['solid_geometry'])

        # Slots
        for slot in self.slots:
            slot['stop'] = affinity.translate(slot['stop'], xoff=dx, yoff=dy)
            slot['start'] = affinity.translate(slot['start'], xoff=dx, yoff=dy)

        # Recreate geometry
        self.create_geometry()
        self.app.proc_container.new_text = ''

    def mirror(self, axis, point):
        """

        :param axis: "X" or "Y" indicates around which axis to mirror.
        :type axis: str
        :param point: [x, y] point belonging to the mirror axis.
        :type point: list
        :return: None
        """
        log.debug("flatcamParsers.ParseExcellon.Excellon.mirror()")

        px, py = point
        xscale, yscale = {"X": (1.0, -1.0), "Y": (-1.0, 1.0)}[axis]

        def mirror_geom(obj):
            if type(obj) is list:
                new_obj = []
                for g in obj:
                    new_obj.append(mirror_geom(g))
                return new_obj
            else:
                try:
                    return affinity.scale(obj, xscale, yscale, origin=(px, py))
                except AttributeError:
                    return obj

        # Modify data

        # variables to display the percentage of work done
        self.geo_len = 0
        try:
            for g in self.drills:
                self.geo_len += 1
        except TypeError:
            self.geo_len = 1
        self.old_disp_number = 0
        self.el_count = 0

        # Drills
        for drill in self.drills:
            drill['point'] = affinity.scale(drill['point'], xscale, yscale, origin=(px, py))

            self.el_count += 1
            disp_number = int(np.interp(self.el_count, [0, self.geo_len], [0, 100]))
            if self.old_disp_number < disp_number <= 100:
                self.app.proc_container.update_view_text(' %d%%' % disp_number)
                self.old_disp_number = disp_number

        # mirror solid_geometry
        for tool in self.tools:
            self.tools[tool]['solid_geometry'] = mirror_geom(self.tools[tool]['solid_geometry'])

        # Slots
        for slot in self.slots:
            slot['stop'] = affinity.scale(slot['stop'], xscale, yscale, origin=(px, py))
            slot['start'] = affinity.scale(slot['start'], xscale, yscale, origin=(px, py))

        # Recreate geometry
        self.create_geometry()
        self.app.proc_container.new_text = ''

    def skew(self, angle_x=None, angle_y=None, point=None):
        """
        Shear/Skew the geometries of an object by angles along x and y dimensions.
        Tool sizes, feedrates an Z-plane dimensions are untouched.

        Parameters
        ----------
        xs, ys : float, float
            The shear angle(s) for the x and y axes respectively. These can be
            specified in either degrees (default) or radians by setting
            use_radians=True.

        See shapely manual for more information:
        http://toblerity.org/shapely/manual.html#affine-transformations
        """
        log.debug("flatcamParsers.ParseExcellon.Excellon.skew()")

        if angle_x is None:
            angle_x = 0.0

        if angle_y is None:
            angle_y = 0.0

        if angle_x == 0 and angle_y == 0:
            return

        def skew_geom(obj):
            if type(obj) is list:
                new_obj = []
                for g in obj:
                    new_obj.append(skew_geom(g))
                return new_obj
            else:
                try:
                    return affinity.skew(obj, angle_x, angle_y, origin=(px, py))
                except AttributeError:
                    return obj

        # variables to display the percentage of work done
        self.geo_len = 0
        try:
            for g in self.drills:
                self.geo_len += 1
        except TypeError:
            self.geo_len = 1
        self.old_disp_number = 0
        self.el_count = 0

        if point is None:
            px, py = 0, 0

            # Drills
            for drill in self.drills:
                drill['point'] = affinity.skew(drill['point'], angle_x, angle_y,
                                               origin=(px, py))

                self.el_count += 1
                disp_number = int(np.interp(self.el_count, [0, self.geo_len], [0, 100]))
                if self.old_disp_number < disp_number <= 100:
                    self.app.proc_container.update_view_text(' %d%%' % disp_number)
                    self.old_disp_number = disp_number

            # skew solid_geometry
            for tool in self.tools:
                self.tools[tool]['solid_geometry'] = skew_geom(self.tools[tool]['solid_geometry'])

            # Slots
            for slot in self.slots:
                slot['stop'] = affinity.skew(slot['stop'], angle_x, angle_y, origin=(px, py))
                slot['start'] = affinity.skew(slot['start'], angle_x, angle_y, origin=(px, py))
        else:
            px, py = point
            # Drills
            for drill in self.drills:
                drill['point'] = affinity.skew(drill['point'], angle_x, angle_y,
                                               origin=(px, py))

                self.el_count += 1
                disp_number = int(np.interp(self.el_count, [0, self.geo_len], [0, 100]))
                if self.old_disp_number < disp_number <= 100:
                    self.app.proc_container.update_view_text(' %d%%' % disp_number)
                    self.old_disp_number = disp_number

            # skew solid_geometry
            for tool in self.tools:
                self.tools[tool]['solid_geometry'] = skew_geom(self.tools[tool]['solid_geometry'])

            # Slots
            for slot in self.slots:
                slot['stop'] = affinity.skew(slot['stop'], angle_x, angle_y, origin=(px, py))
                slot['start'] = affinity.skew(slot['start'], angle_x, angle_y, origin=(px, py))

        self.create_geometry()
        self.app.proc_container.new_text = ''

    def rotate(self, angle, point=None):
        """
        Rotate the geometry of an object by an angle around the 'point' coordinates
        :param angle:
        :param point: tuple of coordinates (x, y)
        :return:
        """
        log.debug("flatcamParsers.ParseExcellon.Excellon.rotate()")

        if angle == 0:
            return

        def rotate_geom(obj, origin=None):
            if type(obj) is list:
                new_obj = []
                for g in obj:
                    new_obj.append(rotate_geom(g))
                return new_obj
            else:
                if origin:
                    try:
                        return affinity.rotate(obj, angle, origin=origin)
                    except AttributeError:
                        return obj
                else:
                    try:
                        return affinity.rotate(obj, angle, origin=(px, py))
                    except AttributeError:
                        return obj

        # variables to display the percentage of work done
        self.geo_len = 0
        try:
            for g in self.drills:
                self.geo_len += 1
        except TypeError:
            self.geo_len = 1
        self.old_disp_number = 0
        self.el_count = 0

        if point is None:
            # Drills
            for drill in self.drills:
                drill['point'] = affinity.rotate(drill['point'], angle, origin='center')

            # rotate solid_geometry
            for tool in self.tools:
                self.tools[tool]['solid_geometry'] = rotate_geom(self.tools[tool]['solid_geometry'], origin='center')

                self.el_count += 1
                disp_number = int(np.interp(self.el_count, [0, self.geo_len], [0, 100]))
                if self.old_disp_number < disp_number <= 100:
                    self.app.proc_container.update_view_text(' %d%%' % disp_number)
                    self.old_disp_number = disp_number

            # Slots
            for slot in self.slots:
                slot['stop'] = affinity.rotate(slot['stop'], angle, origin='center')
                slot['start'] = affinity.rotate(slot['start'], angle, origin='center')
        else:
            px, py = point
            # Drills
            for drill in self.drills:
                drill['point'] = affinity.rotate(drill['point'], angle, origin=(px, py))

                self.el_count += 1
                disp_number = int(np.interp(self.el_count, [0, self.geo_len], [0, 100]))
                if self.old_disp_number < disp_number <= 100:
                    self.app.proc_container.update_view_text(' %d%%' % disp_number)
                    self.old_disp_number = disp_number

            # rotate solid_geometry
            for tool in self.tools:
                self.tools[tool]['solid_geometry'] = rotate_geom(self.tools[tool]['solid_geometry'])

            # Slots
            for slot in self.slots:
                slot['stop'] = affinity.rotate(slot['stop'], angle, origin=(px, py))
                slot['start'] = affinity.rotate(slot['start'], angle, origin=(px, py))

        self.create_geometry()
        self.app.proc_container.new_text = ''