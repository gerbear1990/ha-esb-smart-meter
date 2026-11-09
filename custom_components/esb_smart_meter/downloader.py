"""ESB Networks CSV downloader.

This is adapted from the public badger707 ESB downloader flow, wrapped as a
callable helper for Home Assistant. ESB applies human-verification and login
rate limits, so this should be scheduled conservatively.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from time import sleep

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0"


class ESBDownloadError(RuntimeError):
    """Raised when the ESB portal download flow fails."""


@dataclass(frozen=True)
class ESBDownloadResult:
    """Downloaded ESB CSV data."""

    csv_text: str
    filename: str | None
    rows: int


def download_latest_csv(username: str, password: str, mprn: str) -> ESBDownloadResult:
    """Log in to ESB Networks and download interval CSV data."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        response_1 = session.get(
            "https://myaccount.esbnetworks.ie/",
            allow_redirects=True,
            timeout=(10, 10),
        )
        response_1.raise_for_status()
        settings_match = re.findall(r"(?<=var SETTINGS = )\S*;", response_1.text)
        if not settings_match:
            raise ESBDownloadError("ESB login page did not contain expected settings.")
        settings = json.loads(settings_match[0][:-1])
        cookies_1 = session.cookies.get_dict()

        sleep(10)
        response_2 = session.post(
            "https://login.esbnetworks.ie/esbntwkscustportalprdb2c01.onmicrosoft.com/"
            "B2C_1A_signup_signin/SelfAsserted?tx="
            + settings["transId"]
            + "&p=B2C_1A_signup_signin",
            data={
                "signInName": username,
                "password": password,
                "request_type": "RESPONSE",
            },
            headers={
                "x-csrf-token": settings["csrf"],
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://login.esbnetworks.ie",
                "Dnt": "1",
                "Sec-Gpc": "1",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            cookies={
                "x-ms-cpim-csrf": cookies_1.get("x-ms-cpim-csrf"),
                "x-ms-cpim-trans": cookies_1.get("x-ms-cpim-trans"),
            },
            allow_redirects=False,
            timeout=(10, 10),
        )
        response_2.raise_for_status()
        cookies_2 = session.cookies.get_dict()

        response_3 = session.get(
            "https://login.esbnetworks.ie/esbntwkscustportalprdb2c01.onmicrosoft.com/"
            "B2C_1A_signup_signin/api/CombinedSigninAndSignup/confirmed",
            params={
                "rememberMe": False,
                "csrf_token": settings["csrf"],
                "tx": settings["transId"],
                "p": "B2C_1A_signup_signin",
            },
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Dnt": "1",
                "Sec-Gpc": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
            },
            cookies={
                "x-ms-cpim-csrf": cookies_2.get("x-ms-cpim-csrf"),
                "x-ms-cpim-trans": cookies_2.get("x-ms-cpim-trans"),
            },
            timeout=(10, 10),
        )
        response_3.raise_for_status()
        if response_3.text[0:21] != "<!DOCTYPE html PUBLIC":
            raise ESBDownloadError(
                "ESB did not complete login. Human verification or login limit may be active."
            )

        soup = BeautifulSoup(response_3.content, "html.parser")
        form = soup.find("form", {"id": "auto"})
        if form is None:
            raise ESBDownloadError("ESB login response did not include the expected auto form.")

        sleep(2)
        response_4 = session.post(
            form["action"],
            allow_redirects=False,
            data={
                "state": form.find("input", {"name": "state"})["value"],
                "client_info": form.find("input", {"name": "client_info"})["value"],
                "code": form.find("input", {"name": "code"})["value"],
            },
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://login.esbnetworks.ie",
                "Referer": "https://login.esbnetworks.ie/",
                "Dnt": "1",
                "Sec-Gpc": "1",
            },
            timeout=(10, 10),
        )
        response_4.raise_for_status()
        cookies_4 = session.cookies.get_dict()

        response_5 = session.get(
            "https://myaccount.esbnetworks.ie",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://login.esbnetworks.ie/",
            },
            cookies={
                "ARRAffinity": cookies_4.get("ARRAffinity"),
                "ARRAffinitySameSite": cookies_4.get("ARRAffinitySameSite"),
            },
            timeout=(10, 10),
        )
        response_5.raise_for_status()
        cookies_5 = session.cookies.get_dict()

        sleep(3)
        response_6 = session.get(
            "https://myaccount.esbnetworks.ie/energymanagement/historic-consumption",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://myaccount.esbnetworks.ie/",
            },
            cookies={
                "ARRAffinity": cookies_4.get("ARRAffinity"),
                "ARRAffinitySameSite": cookies_4.get("ARRAffinitySameSite"),
                ".AspNetCore.Cookies": cookies_5.get(".AspNetCore.Cookies"),
            },
            timeout=(10, 10),
        )
        response_6.raise_for_status()

        response_7 = session.get(
            "https://myaccount.esbnetworks.ie/af/t",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "X-Returnurl": "https://myaccount.esbnetworks.ie/energymanagement/historic-consumption",
                "Referer": "https://myaccount.esbnetworks.ie/energymanagement/historic-consumption",
            },
            cookies={
                "ARRAffinity": cookies_4.get("ARRAffinity"),
                "ARRAffinitySameSite": cookies_4.get("ARRAffinitySameSite"),
            },
            timeout=(10, 10),
        )
        response_7.raise_for_status()
        token = json.loads(response_7.text)["token"]

        response_8 = session.post(
            "https://myaccount.esbnetworks.ie/energymanagement/api/consumption/DownloadHdfPeriodic",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://myaccount.esbnetworks.ie/energymanagement/historic-consumption",
                "Content-Type": "application/json",
                "X-Returnurl": "https://myaccount.esbnetworks.ie/energymanagement/historic-consumption",
                "X-Xsrf-Token": token,
                "Origin": "https://myaccount.esbnetworks.ie",
            },
            json={"mprn": mprn, "searchType": "intervalkw"},
            timeout=(10, 30),
        )
        response_8.raise_for_status()
        csv_text = response_8.content.decode("utf-8-sig")
        if not csv_text.startswith("MPRN"):
            raise ESBDownloadError("ESB response did not look like an interval CSV.")

        rows = sum(1 for _ in csv.DictReader(csv_text.splitlines()))
        disposition = response_8.headers.get("Content-Disposition")
        filename = None
        if disposition:
            parts = disposition.split(";")
            if len(parts) > 1 and "=" in parts[1]:
                filename = parts[1].split("=", 1)[1].strip().strip('"')
        return ESBDownloadResult(csv_text=csv_text, filename=filename, rows=rows)
    except requests.RequestException as err:
        raise ESBDownloadError(f"ESB request failed: {err}") from err
    finally:
        session.close()
