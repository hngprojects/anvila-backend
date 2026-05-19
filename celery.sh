#!/bin/bash

APP="app.worker.celery_app:celery_app"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$SCRIPT_DIR/.celery.pid"
LOGFILE="$SCRIPT_DIR/.celery.log"

case "$1" in
start)
    if [ -f "$PIDFILE" ]; then
        pid="$(cat "$PIDFILE" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "Celery already running (PID: $pid)"
            exit 0
        fi
        rm -f "$PIDFILE"
    fi
    echo "Starting Celery worker..."
    if ! celery -A "$APP" worker -l info --pidfile="$PIDFILE" --logfile="$LOGFILE" --detach; then
        echo "Failed to start Celery worker."
        exit 1
    fi
    for _ in {1..30}; do
        if [ -f "$PIDFILE" ]; then
            pid="$(cat "$PIDFILE" 2>/dev/null)"
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                echo "Started. PID: $pid"
                exit 0
            fi
        fi
        sleep 0.1
    done
    echo "Start command returned, but PID file was not created."
    exit 1
    ;;
stop)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "Stopping Celery..."
        pid="$(cat "$PIDFILE")"
        if kill "$pid"; then
            for _ in {1..20}; do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.25
            done
            if kill -0 "$pid" 2>/dev/null; then
                echo "Failed to stop Celery (PID: $pid)"
                exit 1
            fi
            rm -f "$PIDFILE"
            echo "Stopped."
        else
            echo "Failed to send stop signal."
            exit 1
        fi
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
