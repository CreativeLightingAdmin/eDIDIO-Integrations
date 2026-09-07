# edidio_frames.tcl - pure-Tcl eDIDIO protocol frame encoder (zero dependencies).
#
# For Vivado / Quartus Tcl consoles and any tclsh: build eDIDIO frames as binary
# strings and send them over a socket to automate lighting during hardware-in-the-
# loop (HIL) testing. Byte-identical to every other eDIDIO encoder (verified by
# test/test_frames.tcl against the shared reference frames).
#
# Wire format: 0xCD + 2-byte big-endian length + a serialized EdidioMessage.

namespace eval edidio {
    # enums
    variable DALI_ARC_LEVEL 0
    variable DALI_GROUP_ARC_LEVEL 2
    variable DALI_BROADCAST_SCENE 3
    variable DALI_SCENE_ON_GROUP 4
    # DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
    # broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
    # sent to the target address.
    variable GROUP_ADDRESS_BASE 64
    variable BROADCAST_ADDRESS 80
    variable GO_TO_SCENE_BASE 16
    variable DALI_OFF 0
    variable DALI_MAX_LEVEL 5
    variable DALI_MIN_LEVEL 6
    variable SPEKTRA_SEQUENCE 1
    variable SPEKTRA_THEME 2
    variable SPEKTRA_STATIC 3
    variable SPEKTRA_START 0
    variable SPEKTRA_STOP 1
    variable SPEKTRA_PAUSE 2
    variable TRIGGER_SPEKTRA_STOP_SEQ 13
    variable ARC_LEVEL_MAX 254
}

# Encode an unsigned int as a protobuf varint (returns a binary string).
proc edidio::varint {v} {
    set out ""
    while {$v >= 128} {
        append out [binary format c [expr {($v & 0x7f) | 0x80}]]
        set v [expr {$v >> 7}]
    }
    append out [binary format c [expr {$v & 0x7f}]]
    return $out
}

proc edidio::tag {field wire} {
    return [edidio::varint [expr {($field << 3) | $wire}]]
}

# A varint field, omitted when 0 unless always=1.
proc edidio::uintf {field value {always 0}} {
    if {$value == 0 && !$always} { return "" }
    return "[edidio::tag $field 0][edidio::varint $value]"
}

# A length-delimited embedded field.
proc edidio::embed {field body} {
    return "[edidio::tag $field 2][edidio::varint [string length $body]]$body"
}

# Wrap a serialized EdidioMessage body with the 0xCD + 2-byte length header.
proc edidio::frame {body} {
    set n [string length $body]
    return "[binary format c 0xCD][binary format S $n]$body"
}

proc edidio::clamp {v lo hi} {
    if {$v < $lo} { return $lo }
    if {$v > $hi} { return $hi }
    return $v
}

# 1-based line (1-4) -> single-bit mask.
proc edidio::line_mask {line} { return [expr {1 << ($line - 1)}] }

proc edidio::_dali {mid line_mask address command custom arg} {
    set body [edidio::uintf 1 $line_mask]
    append body [edidio::uintf 2 $address]
    if {$command >= 0}  { append body [edidio::uintf 5 $command 1] }
    if {$custom >= 0}   { append body [edidio::uintf 6 $custom 1] }
    if {$arg >= 0}      { append body [edidio::uintf 9 $arg 1] }
    set edidio "[edidio::uintf 1 $mid][edidio::embed 18 $body]"
    return [edidio::frame $edidio]
}

proc edidio::dali_arc_level {mid line_mask address level} {
    return [edidio::_dali $mid $line_mask $address -1 $edidio::DALI_ARC_LEVEL [edidio::clamp $level 0 $edidio::ARC_LEVEL_MAX]]
}
proc edidio::dali_group_arc_level {mid line_mask group level} {
    # DALI_ARC_LEVEL to the group address (64 + group).
    return [edidio::_dali $mid $line_mask [expr {$edidio::GROUP_ADDRESS_BASE + $group}] -1 $edidio::DALI_ARC_LEVEL [edidio::clamp $level 0 $edidio::ARC_LEVEL_MAX]]
}
proc edidio::dali_command {mid line_mask address command {arg 0}} {
    return [edidio::_dali $mid $line_mask $address $command -1 $arg]
}
proc edidio::dali_broadcast_scene {mid line_mask scene} {
    # Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
    return [edidio::_dali $mid $line_mask $edidio::BROADCAST_ADDRESS [expr {$edidio::GO_TO_SCENE_BASE + $scene}] -1 -1]
}
proc edidio::dali_scene_on_group {mid line_mask group scene} {
    # Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
    return [edidio::_dali $mid $line_mask [expr {$edidio::GROUP_ADDRESS_BASE + $group}] [expr {$edidio::GO_TO_SCENE_BASE + $scene}] -1 -1]
}

# levels is a Tcl list of 0-255 ints.
proc edidio::dmx_level {mid zone universe_mask channel repeat levels {fade_by_10ms 0}} {
    set packed ""
    foreach lv $levels { append packed [edidio::varint [edidio::clamp $lv 0 255]] }
    set body [edidio::uintf 1 $zone]
    append body [edidio::uintf 2 $universe_mask]
    append body [edidio::uintf 3 $channel]
    append body [edidio::uintf 4 $repeat]
    append body "[edidio::tag 5 2][edidio::varint [string length $packed]]$packed"
    append body [edidio::uintf 6 $fade_by_10ms]
    set edidio "[edidio::uintf 1 $mid][edidio::embed 20 $body]"
    return [edidio::frame $edidio]
}

proc edidio::spektra_control {mid type zone index action} {
    set body [edidio::uintf 1 $type]
    append body [edidio::uintf 2 $zone]
    append body [edidio::uintf 3 $index]
    append body [edidio::uintf 4 $action]
    set edidio "[edidio::uintf 1 $mid][edidio::embed 27 $body]"
    return [edidio::frame $edidio]
}

proc edidio::spektra_stop {mid zone {line_mask 255}} {
    set trigger [edidio::uintf 1 $edidio::TRIGGER_SPEKTRA_STOP_SEQ]
    append trigger [edidio::uintf 2 $zone]
    append trigger [edidio::uintf 3 $line_mask]
    set external [edidio::embed 1 $trigger]
    set edidio "[edidio::uintf 1 $mid][edidio::embed 21 $external]"
    return [edidio::frame $edidio]
}

# Keep-alive frame.
proc edidio::keep_alive {} {
    return "[binary format c 0xFF][binary format c 0xF6]"
}

# --- convenience: open a connection and send framed messages ---------------
# Usage:
#   set sock [edidio::connect 192.168.1.50]
#   edidio::send $sock [edidio::dali_arc_level 1 [edidio::line_mask 1] 5 254]
proc edidio::connect {host {port 23}} {
    set sock [socket $host $port]
    fconfigure $sock -translation binary -buffering none
    return $sock
}
proc edidio::send {sock frame} {
    puts -nonewline $sock $frame
    flush $sock
}
