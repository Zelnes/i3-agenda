from __future__ import print_function

import csv
import json
import sys

import subprocess
import re
import bs4
from i3_agenda import config

from typing import List, Optional
import datetime

from i3_agenda.event import Event, get_closest, sort_events, get_future_events

from markupsafe import escape

from typing import Union
from i3_agenda.const import (
    LEFT_MOUSE_BUTTON,
    RIGHT_MOUSE_BUTTON,
)

DEFAULT_CAL_WEBPAGE = "https://calendar.google.com/calendar/r/day"


def run_open(link: str | None):
    if link:
        print(f"Opening link: {link}")
        subprocess.Popen(["xdg-open", link])
    else:
        print("No link to open")

def button_action(button_code: str, closest: Event):
    if button_code != "":
        if button_code == LEFT_MOUSE_BUTTON:
            run_open(DEFAULT_CAL_WEBPAGE)
        elif button_code == RIGHT_MOUSE_BUTTON:
            if closest.location:
                run_open(closest.location)


def filter_only_todays_events(events: List[Event]) -> Optional[List[Event]]:
    now = datetime.datetime.now()
    midnight_rfc3339 = now.replace(hour=23, minute=59, second=59)
    return list(
        filter(
            lambda event: datetime.datetime.fromtimestamp(event.start_time)
            < midnight_rfc3339,
            events,
        )
    )


def load_events(args) -> List[Event]:
    from i3_agenda.api import get_events
    from i3_agenda.cache_utils import load_cache, save_cache

    events: Union[None, list[Event]] = None

    if not args.update:
        events = load_cache(args.cachettl)
        if args.today:
            if events:
                events = filter_only_todays_events(events)

    if events is None or args.update:
        events = get_events(
            args.credentials, args.ids, args.maxres, args.today
        )
        save_cache(events)
    return events

def extract_zoom_link(event: Event) -> Optional[str]:
    """
    Extracts the Zoom link from the event.
    Searches in the location first, then in the description.

    This function only handles Zoom links.
    """

    def is_zoom_url_and_converted(url: str | None) -> str | None:
        if url and "https://us02web.zoom.us/j/" in url:
            split = re.split('[/?=]', url)
            meeting_id = split[-3]
            password = split[-1]
            return f"zoommtg://zoom.us/join?action=join&confno={meeting_id}&pwd={password}"
        return None

    link = is_zoom_url_and_converted(event.location)

    if link is not None:
        return link

    parsed_html = bs4.BeautifulSoup(event.description, "html.parser")

    for item in parsed_html.find_all("br"):
        next = item.next_sibling
        if type(next) is bs4.element.NavigableString:
            link = is_zoom_url_and_converted(next)
            if link is not None:
                return link
    else:
        return None

def event_str(event: Event, args):
    return event.get_string(
        args.limchar,
        args.date_format,
        args.ongoing_time_left,
        args.next_event_time_left,
    )

def is_all_day_event(event: Event) -> bool:
    """
    Determine if an event should be considered an all-day event for display purposes.
    Returns True for:
    1. All-day events
    2. Long meetings (>3 hours) without Google Meet links
    """
    # Check if it's an all-day event
    if event.is_allday():
        return True

    # Check if it's a long meeting (>3 hours) without Google Meet link
    duration_hours = (event.end_time - event.start_time) / 3600  # Convert seconds to hours
    print(f"Event '{event.summary}' duration: {duration_hours} hours", file=sys.stderr)
    return duration_hours > 3
    if duration_hours > 3:
        # Check if it has a Google Meet link (hangoutLink would be in location)
        has_google_meet = event.location and "meet.google.com" in event.location
        if not has_google_meet:
            return True

    return False

def format_allday_events_section(allday_events: List[Event], args) -> str:
    """
    Format all-day events with a header and line separator.
    """
    if not allday_events:
        return ""

    formatted_events = []
    formatted_events.append("All day events")
    formatted_events.append("─" * 15)  # Unicode line separator

    for event in allday_events:
        # For all-day events, show just the name and date info
        event_line = event_str(event, args)
        formatted_events.append(event_line)

    return "\n".join(formatted_events)

def print_all(events: List[Event], args):
    if args.format == 'i3blocks':
        # Filter out declined events
        accepted_events = [event for event in events if not event.is_declined()]
        for event in accepted_events:
            print(event_str(event, args))
    elif args.format == 'waybar':
        # Filter out declined events first
        accepted_events = [event for event in events if not event.is_declined()]

        # Separate regular events from all-day events
        regular_events = [event for event in accepted_events if not is_all_day_event(event)]
        allday_events = [event for event in accepted_events if is_all_day_event(event)]

        if not accepted_events:
            print(json.dumps({"text": args.no_event_text}))
        elif not regular_events:
            # Only all-day events exist, show count in main text
            count = len(allday_events)
            event_word = "event" if count == 1 else "events"
            allday_section = format_allday_events_section(allday_events, args)
            print(
                json.dumps({
                    "text": f"{count} all-day {event_word}",
                    "tooltip": allday_section,
                })
            )
        else:
            # Show regular events with first one as main text, rest + all-day events in tooltip
            tooltip_parts = []

            # Add remaining regular events to tooltip
            if len(regular_events) > 1:
                tooltip_parts.extend(event_str(e, args) for e in regular_events[1:])

            # Add all-day events section at the end if any exist
            allday_section = format_allday_events_section(allday_events, args)
            if allday_section:
                # Add separator between regular and all-day events if there are regular events in tooltip
                if tooltip_parts:
                    tooltip_parts.append("")  # Empty line for separation
                tooltip_parts.append(allday_section)

            print(
                json.dumps({
                    "text": f"  {escape(event_str(regular_events[0], args))}",
                    "tooltip": "\n".join(tooltip_parts),
                })
            )

def main():
    args = config.parser.parse_args()
    config.CONF_DIR = args.conf

    events = sort_events(load_events(args))

    events = get_future_events(
        events, args.hide_event_after, args.show_event_before
    )

    if args.print_all:
        print_all(events, args)
        return

    if args.skip > 0:
        events = sort_events(events)
        events = events[args.skip:]

    closest = get_closest(events)
    if closest is None:
        print(args.no_event_text)
        return

    button_action(config.button, closest)

    if args.open_link:
        link = None
        print(closest)
        if args.search_zoom_link:
            link = extract_zoom_link(closest)
        if link is None:
            link = closest.location

        run_open(link)
    else:
        print(
            closest.get_string(
                args.limchar,
                args.date_format,
                args.ongoing_time_left,
                args.next_event_time_left,
            )
        )

    if closest.is_urgent():
        # special i3blocks exit code to set the block urgent
        exit(33)


if __name__ == "__main__":
    main()
