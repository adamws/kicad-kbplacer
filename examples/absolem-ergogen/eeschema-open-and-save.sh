#!/bin/sh
eeschema $1 &
EESCHEMA_PID=$!
sleep 1
xdotool key Return
sleep 1
xdotool key Return
sleep 2
xdotool key ctrl+s
sleep 2
kill -9 $EESCHEMA_PID
