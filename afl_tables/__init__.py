from urllib.parse import urljoin
import requests
import bs4
import re
import datetime
import itertools
import typing
from bs4 import BeautifulSoup
from pytz import timezone

BASE_URL = 'https://afltables.com/afl/'
AEST = timezone('Australia/Melbourne')


def grouper(n, iterable, fillvalue=None):
    """
    Chunks an iterable into chunks of size n
    """
    args = [iter(iterable)] * n
    return itertools.zip_longest(fillvalue=fillvalue, *args)


class MatchException(Exception):
    pass


class Score:
    # ... (unchanged class code) ...
    def __init__(self, goals, behinds):
        self.goals = goals
        self.behinds = behinds

    @classmethod
    def parse(cls, pointstring: str) -> 'Score':
        goals, behinds = pointstring.replace('(', '').replace(')', '').split('.')
        return Score(int(goals), int(behinds))

    @property
    def score(self) -> int:
        return 6 * self.goals + self.behinds

    def __str__(self):
        return f'{self.goals}.{self.behinds}'


class TeamMatch:
    # ... (unchanged class code) ...
    def __init__(self, name: str, match: 'Match', scores: typing.List[Score] = []):
        self.name = name
        self.scores = scores
        self.match = match

    @property
    def final_score(self) -> typing.Optional[Score]:
        if self.match.bye:
            return None
        else:
            return self.scores[-1]

    @classmethod
    def parse_bye(cls, name: bs4.Tag, match: 'Match'):
        return cls(name=name.text, match=match)

    @classmethod
    def parse_match(cls, name: bs4.Tag, rounds: bs4.Tag, match: 'Match'):
        return cls(name=name.text, scores=[Score.parse(s) for s in rounds.text.split()], match=match)

    def __str__(self):
        if self.match.bye:
            return f'{self.name} Bye'
        else:
            return f'{self.name} {self.final_score}'


class Match:
    # ... (unchanged class docstring) ...
    def __init__(self,
                 teams: typing.List[TeamMatch],
                 winner: str,
                 attendees: int = None,
                 date: datetime = None,
                 venue: str = None,
                 bye: bool = False):
        self.teams = teams
        self.attendees = attendees
        self.date = date
        self.venue = venue
        self.bye = bye
        self.winner = winner

    @staticmethod
    def _parse_misc(misc: bs4.Tag) -> dict:
        ret = {}

        # DEBUG: Show all contents of misc
        for i, c in enumerate(misc.contents):
            print(f"misc.contents[{i}]: {repr(c)}")

        try:
            raw = ' '.join(str(c) for c in misc.contents).strip()
            print(f"DEBUG: raw date string: {raw}")

            match = re.search(r'(?P<date>\w{3} \d{2}-\w{3}-\d{4})(?:[^\d]*(?P<time>\d{1,2}:\d{2} [AP]M))?', raw)

            if match:
                date_part = match.group('date')
                time_part = match.group('time')

                print(f"DEBUG: parsed date = {date_part}, time = {time_part}")

                if time_part:
                    parsed_date = datetime.datetime.strptime(f"{date_part} {time_part}", '%a %d-%b-%Y %I:%M %p').replace(tzinfo=AEST)
                else:
                    parsed_date = datetime.datetime.strptime(date_part, '%a %d-%b-%Y').replace(tzinfo=AEST)
            else:
                print(f"Could not extract date from: {raw}")
                parsed_date = None

            ret['date'] = parsed_date

        except Exception as e:
            print(f"Date parse error: {e} | Raw: {raw}")
            ret['date'] = None

        misc_attr = None
        for element in misc.contents[1:]:
            if 'Venue' in str(element):
                misc_attr = 'venue'
            elif 'Att' in str(element):
                misc_attr = 'attendees'
            elif len(str(element).strip()) > 0:
                if misc_attr == 'venue':
                    ret['venue'] = element.text
                elif misc_attr == 'attendees':
                    ret['attendees'] = int(str(element).replace(',', '').replace(' ', ''))
                misc_attr = None

        return ret

    @classmethod
    def parse(cls, table: bs4.Tag):
        td = table.find_all('td')

        if len(td) == 8:
            team_1, team_1_stats, team_1_score, misc, team_2, team_2_stats, team_2_score, winner = td
            misc_kwargs = cls._parse_misc(misc)

            match = cls(
                [],
                bye=False,
                winner=winner.b.text,
                **misc_kwargs
            )

            match.teams = [
                TeamMatch.parse_match(team_1, team_1_stats, match),
                TeamMatch.parse_match(team_2, team_2_stats, match)
            ]

            return match
        elif len(td) == 2:
            match = cls([], bye=True, winner=td[0].text)
            match.teams = [TeamMatch.parse_bye(td[0], match)]
            return match
        else:
            raise MatchException('This is invalid markup for a Match object')

    def __str__(self):
        if self.bye:
            return f'{self.teams[0].name} vs Bye'
        else:
            return f'{self.teams[0].name} vs {self.teams[1].name}'


class Round:
    # ... (unchanged class code) ...
    def __init__(self, title: str, matches: list = []):
        self.title = title
        self.matches = matches

    @classmethod
    def parse(cls, title: bs4.Tag, table: bs4.Tag) -> 'Round':
        title = title.text

        if 'Final' in title:
            matches = [Match.parse(table)]
        else:
            matches = []
            for match in table.select('td[width="85%"] table'):
                try:
                    matches.append(Match.parse(match))
                except MatchException:
                    continue

        return cls(title=title, matches=matches)

    def __str__(self):
        return self.title


class MatchScraper:
    @staticmethod
    def _url(year: int):
        return urljoin(BASE_URL, f'seas/{year}.html')

    @classmethod
    def scrape(cls, year: int) -> typing.List[Round]:
        url = cls._url(year)
        rounds = []
        html = requests.get(url).text
        soup = BeautifulSoup(html, 'html5lib')

        tables = [table for table in soup.select('center > table') if
                  table.get('class') != ['sortable'] and table.text != 'Finals']

        for header, body in grouper(2, tables):
            title = header.find('td')
            rounds.append(Round.parse(title, body))

        return rounds
