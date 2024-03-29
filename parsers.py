from datetime import date, datetime, timezone
from dateutil import tz
from dateutil.relativedelta import relativedelta
import json
import requests
import re


class ChesscomParser:
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    CONTENT_TYPE = "application/x-chess-pgn"
    UTC_ZONE = tz.tzutc()
    LOCAL_ZONE = tz.tzlocal()

    def __init__(self, username) -> None:
        self.username = username
        self.pgn_list = []
        self.pgn_tags = []

    def _create_headers(self) -> dict:
        """
        A simple utility function that creates the necessary headers for each API call
        in order to reduce code redundancy.
        """
        return {
            "User-Agent": self.USER_AGENT,
            "content_type": self.CONTENT_TYPE,
            "Content-Disposition": f'attachment; filename="ChessCom_{self.username}_{datetime.today():%Y%m}.pgn"',
        }

    def convert_utc_to_local(self, date, time):
        """
        Takes in the UTC date and time as written in the PGN text fetched from the
        chess.com server, returns a tuple of date and time as string with the
        formatting (YYYY/MM/DD, HH:MM:SS).
        """
        utc = datetime.strptime(f"{date} {time}", "%Y.%m.%d %H:%M:%S")
        utc = utc.replace(tzinfo=self.UTC_ZONE)
        local = utc.astimezone(self.LOCAL_ZONE)
        date, time = datetime.strftime(local, "%Y/%m/%d %H:%M:%S").split()
        return date, time

    def extract_pgn_tags(self) -> list:
        """
        Takes in a PGN string from the fetched games and uses regex to extract the headers (tags)
        that are associated with the game.
        """
        tag_pattern = re.compile(r'\[([A-Za-z]+)\s"([^"]+)"\]')
        for game in self.pgn_list:
            match = tag_pattern.findall(game)
            tags = {tag[0].lower(): tag[1] for tag in match}
            moves_start = game.find("\n\n") + 2
            # This sort of complex line uses the above start index of the moves in the PGN
            # string to slice out all of the moves and then uses re.sub to remove the
            # clock notation that is default in PGNs from chess.com. It also removes the
            # notation for black moves to make it consistent with PGNs from lichess.org
            tags["moves"] = re.sub(r"{\S+ \S+}", "", game[moves_start:].strip())
            tags["moves"] = re.sub(r"\s\d+\.\.\.\s", "", tags["moves"])
            self.pgn_tags.append(tags)
        return self

    def generate_supplemental_tags(self) -> dict:
        """
        Takes the existing tags that are generated by chess.com and uses them to generate desirable
        information not found in default tags (i.e. game ID and local date/time).
        """
        for game in self.pgn_tags:
            # Generates tags for local date and local time
            game["localdate"], game["localtime"] = self.convert_utc_to_local(
                game["utcdate"], game["utctime"]
            )

            # Extracts tag for game ID
            game["game_id"] = re.search(r".+/(\d+)", game["link"])[1]

            # Determines overall result of the game
            split_termination = game["termination"].split()
            if split_termination[0] == "seanyseand":
                game["result"] = "win"
            elif game["result"] == "Game":
                game["result"] = "draw"
            else:
                game["result"] = "loss"
            ending = " ".join(split_termination[-2:])

            # Gets reason for ending of game
            match ending:
                case "by checkmate":
                    game["ending"] = "checkmate"
                case "by resignation":
                    game["ending"] = "resignation"
                case "on time":
                    game["ending"] = "time"
                case "by repetition":
                    game["ending"] = "draw"
                case "by stalemate":
                    game["ending"] = "stalemate"
                case "insufficient material":
                    game["ending"] = "draw"
                case "game abandoned":
                    game["ending"] = "abandoned"

            # Finds the rating differential relative to me
            if game["white"] == "seanyseand":
                game["elodiff"] = int(game["whiteelo"]) - int(game["blackelo"])
            else:
                game["elodiff"] = int(game["blackelo"]) - int(game["whiteelo"])

            # Parses time control information
            if "/" in game["timecontrol"]:
                game["timecategory"] = "daily"
                game["increment"] = "n/a"
            else:
                time_split = int(game["timecontrol"].split("+")[0])
                if time_split >= 600:
                    game["timecategory"] = "rapid"
                elif 60 < time_split < 600:
                    game["timecategory"] = "blitz"
                else:
                    game["timecategory"] = "bullet"
            if "+" in game["timecontrol"]:
                game["increment"] = "yes"
            else:
                game["increment"] = "no"

            # Determines number of moves in the game
            moves_list = re.split(r"\d+\.", game["moves"])
            game["nmoves"] = len([move for move in moves_list if move.strip()])

            # Putting chess.com into lower case
            game["site"] = game["site"].lower()

        return self

    def fetch_current_month_pgns(self) -> list:
        """
        Uses the requests library to fetch the raw multi-game PGN text for
        games played in the month that the script is being run in. Returns a UTF-8
        encoded string.
        """
        url = f"https://api.chess.com/pub/player/{self.username}/games/{(today:=datetime.today()):%Y}/{today:%m}/pgn"
        headers = self._create_headers()
        response = requests.get(url=url, headers=headers)
        response.raise_for_status()
        pgns = response.text
        self.pgn_list = pgns.split("\n\n\n")
        return self.pgn_list

    def fetch_specific_month_pgns(self, date: str) -> list:
        """
        Uses the requests library to fetch the raw multi-game PGN text for
        games played in the specified month. Returns a UTF-8 encoded string.
        """
        year, month = date.split("/")
        url = (
            f"https://api.chess.com/pub/player/{self.username}/games/{year}/{month}/pgn"
        )
        headers = self._create_headers()
        response = requests.get(url=url, headers=headers)
        response.raise_for_status()
        pgns = response.text
        self.pgn_list = pgns.split("\n\n\n")
        return self.pgn_list

    def fetch_month_range_pgns(self, start_in: str, end_in: str) -> list:
        """
        Uses the requests library to fetch the raw multi-game PGN text for
        games played in the specified month. Returns a UTF-8 encoded string.
        """
        month_list = []

        start_year, start_month = start_in.split("/")
        end_year, end_month = end_in.split("/")
        start = date(int(start_year), int(start_month), 1)
        end = date(int(end_year), int(end_month), 1)
        while start <= end:
            month_list.append(start)
            start += relativedelta(months=1)

        pgn_accumulator = ""
        for m in month_list:
            url = f"https://api.chess.com/pub/player/{self.username}/games/{m.year}/{m.month:02d}/pgn"
            headers = self._create_headers()
            response = requests.get(url=url, headers=headers)
            response.raise_for_status()
            if response.text:
                pgn_accumulator += response.text.rstrip()
                pgn_accumulator += "\n\n\n"

        self.pgn_list = pgn_accumulator.rstrip("\n\n\n").split("\n\n\n")

        return self.pgn_list


class LichessParser:
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    ACCEPT = "application/x-ndjson"
    UTC_ZONE = tz.tzutc()
    LOCAL_ZONE = tz.tzlocal()

    def __init__(self, username) -> None:
        self.username = username
        self.json_list = []
        self.pgn_tags = []

    def _create_headers(self) -> dict:
        return {"User-Agent": self.USER_AGENT, "Accept": self.ACCEPT}

    def convert_utc_to_local(self, date, time):
        """
        Takes in the UTC date and time as written in the PGN text fetched from the
        chess.com server, returns a tuple of date and time as string with the
        formatting (YYYY/MM/DD, HH:MM:SS).
        """
        utc = datetime.strptime(f"{date} {time}", "%Y.%m.%d %H:%M:%S")
        utc = utc.replace(tzinfo=self.UTC_ZONE)
        local = utc.astimezone(self.LOCAL_ZONE)
        date, time = datetime.strftime(local, "%Y/%m/%d %H:%M:%S").split()
        return date, time

    def fetch_current_month_jsons(self) -> str:
        """
        Uses the requests library to fetch the raw multi-game PGN text for
        games played in the month that the script is being run in. Returns a UTF-8
        encoded string.
        """
        # First we need to dynamically generate the start and end of the month
        # start = datetime(2022, 1, 1)
        start = datetime((today := datetime.today()).year, today.month, 1)
        end = None
        last = 31
        while not end:
            try:
                end = datetime((today := datetime.today()).year, today.month, last)
            except ValueError:
                last -= 1
        # We need to conver the start and end dates into UNIX epoch timestamps
        # in milliseconds (Python returns in seconds by default)

        start = int(start.replace(tzinfo=timezone.utc).timestamp() * 1000)
        end = int(end.replace(tzinfo=timezone.utc).timestamp() * 1000)
        url = f"https://lichess.org/api/games/user/{self.username}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/x-ndjson",
        }
        query = {
            "since": start,
            "literate": "true",
            "until": end,
            "pgnInJson": "true",
            "tags": "true",
            "lastFen": "true",
            "sort": "dateAsc",
        }
        response = requests.get(url=url, headers=headers, params=query)
        response.raise_for_status()
        raw_data = response.text
        split_json_strings = raw_data.split("\n")[:-1]
        self.json_list = [json.loads(game) for game in split_json_strings]
        return self.json_list

    def extract_pgn_tags_from_json(self, json_pgn) -> list:
        """
        TAKES JSON
        """
        tag_pattern = re.compile(r'\[([A-Za-z]+)\s"([^"]+)"\]')
        match = tag_pattern.findall(json_pgn)
        tags = {tag[0].lower(): tag[1] for tag in match}
        moves_start = json_pgn.find("\n\n") + 2
        tags["moves"] = json_pgn[moves_start:].strip()
        return tags

    def convert_json_list_to_pgn_list(self):
        for json in self.json_list:
            tags = self.extract_pgn_tags_from_json(json["pgn"])
            # Generates tags for local date and local time
            tags["localdate"], tags["localtime"] = self.convert_utc_to_local(
                tags["utcdate"], tags["utctime"]
            )
            tags["game_id"] = json["id"]
            tags["currentposition"] = json["lastFen"]

            tags["ending"] = self.extract_ending_from_pgn(tags["moves"])
            tags["moves"] = re.sub(r"{[^{}]+}", "", tags["moves"])
            tags["moves"] = re.sub(r"\d+\.", r" \g<0>", tags["moves"]).strip()

            if "winner" in json:
                match json["winner"]:
                    case "white":
                        if tags["white"] == "seanyseand":
                            tags["result"] = "win"
                        else:
                            tags["result"] = "loss"
                    case "black":
                        if tags["black"] == "seanyseand":
                            tags["result"] = "win"
                        else:
                            tags["result"] = "loss"
            else:
                tags["result"] = "draw"

            if tags["ending"]:
                self.pgn_tags.append(tags)

            if tags["white"] == "seanyseand":
                try:
                    tags["elodiff"] = tags["whiteratingdiff"]
                except KeyError:
                    tags["elodiff"] = None
            else:
                try:
                    tags["elodiff"] = tags["blackratingdiff"]
                except KeyError:
                    tags["elodiff"] = None

            # Parses time control information
            if tags["timecontrol"] == "-":
                tags["timecategory"] = "daily"
                tags["increment"] = "n/a"
            else:
                time_split = tags["timecontrol"].split("+")
                time = int(time_split[0])
                increment = int(time_split[1])
                if time >= 600:
                    tags["timecategory"] = "rapid"
                elif 60 < time < 600:
                    tags["timecategory"] = "blitz"
                else:
                    tags["timecategory"] = "bullet"

                if increment:
                    tags["increment"] = "yes"
                else:
                    tags["increment"] = "no"

            # Determines number of moves in the game
            moves_list = re.split(r"\d+\.", tags["moves"])
            tags["nmoves"] = len([move for move in moves_list if move.strip()])

        return self

    def extract_ending_from_pgn(self, moves):
        pattern = re.compile(r"{([^{}]+)}")
        try:
            ending = re.findall(pattern, moves)[-1]
        except IndexError:
            return None
        if "resigns" in ending:
            return "resignation"
        elif "checkmate" in ending:
            return "checkmate"
        elif "left" in ending:
            return "abandoned"
        elif "on time" in ending:
            return "time"
        elif "stalemate" in ending:
            return "stalemate"
        elif ("Draw" or "draw") in ending:
            return "draw"
