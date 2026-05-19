#!/bin/bash

PIDFILE=".celery.pid"
LOGFILE=".celery.log"
APP="app.worker.celery_app:celery_app"

case "$1" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Celery already running (PID: $(cat "$PIDFILE"))"
      exit 0
    fi
    echo "Starting Celery worker..."
    celery -A "$APP" worker -l info --pidfile="$PIDFILE" --logfile="$LOGFILE" --detach
    echo "Started. PID: $(cat "$PIDFILE")"
    ;;
  stop)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Stopping Celery..."
      kill "$(cat "$PIDFILE")" && rm -f "$PIDFILE"
      echo "Stopped."
    else
      echo "Not running."
      rm -f "$PIDFILE"
    fi
    ;;
  restart)
    $0 stop
    sleep 1
    $0 start
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Running (PID: $(cat "$PIDFILE"))"
    else
      echo "Not running."
      rm -f "$PIDFILE"
    fi
    ;;
  logs)
    tail -f "$LOGFILE"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
