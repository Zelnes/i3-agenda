from __future__ import print_function

import subprocess
import re
import bs4
from i3_agenda import config

from typing import List, Optional
import datetime

from i3_agenda.event import Event, get_closest, sort_events, get_future_events

from typing import Union
from i3_agenda.const import (
    LEFT_MOUSE_BUTTON,
    RIGHT_MOUSE_BUTTON,
)

DEFAULT_CAL_WEBPAGE = "https://calendar.google.com/calendar/r/day"


def run_open(link: str):
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

    def is_zoom_url_and_converted(url: str) -> bool:
        if "https://us02web.zoom.us/j/" in url:
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


def main():
    args = config.parser.parse_args()
    config.CONF_DIR = args.conf

    events = load_events(args)

    events = get_future_events(
        events, args.hide_event_after, args.show_event_before
    )

    if args.skip > 0:
        events = sort_events(events)
        events = events[args.skip:]

    closest = get_closest(events)
    if closest is None:
        print(args.no_event_text)
        return

    button_action(config.button, closest)

    if args.open_link:
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
