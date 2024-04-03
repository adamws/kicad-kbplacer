#!/bin/sh
eeschema $1 &
EESCHEMA_PID=$!
# long sleeps because it take a while on circleci
sleep 10
xdotool key Return
sleep 5
xdotool key Return
sleep 5
xdotool key ctrl+s
sleep 2
kill -9 $EESCHEMA_PID
