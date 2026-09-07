# Byte-equality test for the Tcl encoder.  tclsh test/test_frames.tcl
# Reference hexes captured from edidio_control_py 0.3.0 (message_id=7).

source [file join [file dirname [info script]] .. edidio_frames.tcl]

set failures 0

proc hexof {bin} {
    binary scan $bin H* hex
    return $hex
}

proc check {name got want} {
    if {$got eq $want} {
        puts "\[ok\]   $name"
    } else {
        puts "\[FAIL\] $name"
        puts "  got:  $got"
        puts "  want: $want"
        incr ::failures
    }
}

set MID 7

check arc          [hexof [edidio::dali_arc_level $MID [edidio::line_mask 1] 5 200]] \
                   "cd000e080792010908011005300048c801"
check group        [hexof [edidio::dali_group_arc_level $MID [edidio::line_mask 1] 3 128]] \
                   "cd000e0807920109080110433000488001"
check cmd          [hexof [edidio::dali_command $MID [edidio::line_mask 2] 10 $edidio::DALI_MAX_LEVEL]] \
                   "cd000d08079201080802100a28054800"
check cmd_off      [hexof [edidio::dali_command $MID [edidio::line_mask 1] 0 $edidio::DALI_OFF]] \
                   "cd000b0807920106080128004800"
check bscene       [hexof [edidio::dali_broadcast_scene $MID [edidio::line_mask 1] 3]] \
                   "cd000b0807920106080110502813"
check gscene       [hexof [edidio::dali_scene_on_group $MID [edidio::line_mask 1] 4 3]] \
                   "cd000b0807920106080110442813"
check dmx          [hexof [edidio::dmx_level $MID 255 2 1 10 {255 0 0}]] \
                   "cd00140807a2010f08ff0110021801200a2a04ff010000"
check dmx_fade     [hexof [edidio::dmx_level $MID 0 1 1 1 {10 20 30} 50]] \
                   "cd00120807a2010d1001180120012a030a141e3032"
check spektra      [hexof [edidio::spektra_control $MID $edidio::SPEKTRA_SEQUENCE 1 2 $edidio::SPEKTRA_START]] \
                   "cd000b0807da0106080110011802"
check spektra_stop [hexof [edidio::spektra_stop $MID 1 255]] \
                   "cd000e0807aa01090a07080d100118ff01"
check keepalive    [hexof [edidio::keep_alive]] "fff6"

puts ""
if {$failures == 0} {
    puts "ALL PASSED"
    exit 0
} else {
    puts "FAILURES PRESENT"
    exit 1
}
