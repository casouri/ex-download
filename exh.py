from requests_html import HTMLSession
import requests
import json
import os
import re
import time

# to where gallaries are saved
GALLARY_ROOT_DIR = './gallary'
# whether to use aria2 downloader
USE_ARIA2 = True
# name of the cookie file
COOKIE_FILE = 'cookie.json'
# seconds wait for between requests (so we are not blocked)
WAIT_INTERVAL = 1

EX_URL = 'https://exhentai.org'
FAV_URL = 'https://exhentai.org/favorites.php'
# GALLARY_LINK_XPATH = '//div[@class = "gl1t"]/a/@href'
GALLARY_LINK_NODE_XPATH = '//div[@class = "gl1t"]/div/div/a'
DOWNLOAD_ARCHIVE_ONCLICK_XPATH = '//a[text() = "Archive Download"]/@onclick'


# you need to escape filenames if you use NTFS
def escape_windows_filename(name):
    """Return a windows-compatible NAME."""
    for char in '<>:"\\/|?*':
        name = name.replace(char, '-')
    return name

def get_gallary_link_and_name(response, gallary_name_list):
    """Get each gallary in RESPONSE and return them as a list.
Only include ones that its name is not in GALLARY_NAME_LIST."""
    node_list = response.html.xpath(GALLARY_LINK_NODE_XPATH)
    if node_list == []:
        raise Exception('Cannot find gallaries html nodes from page at all')
    gallary_link_list = []
    new_gallary_name_list = []
    for node in node_list:
        link = node.attrs['href']
        if link == None:
            raise Exception('Cannot find gallary link from gallary html node')
        name = escape_windows_filename(node.text)
        if name not in gallary_name_list:
            gallary_link_list.append(link)
            new_gallary_name_list.append(name)
    return gallary_link_list, new_gallary_name_list


def get_gallary_name_list(gallary_root_dir):
    """Get a list of gallary names under GALLARY_ROOT_DIR."""
    name_list = []
    for fle in os.listdir(gallary_root_dir):
        if os.path.isfile(os.path.join(gallary_root_dir, fle)):
            name = os.path.splitext(os.path.basename(fle))[0]
            name_list.append(escape_windows_filename(name))
    return name_list


def get_download_link(session, resp, cookie):
    """Get download link from gallary page response."""
    onclick_code = resp.html.xpath(DOWNLOAD_ARCHIVE_ONCLICK_XPATH)[0]
    popup_url = re.search("'(https://.+)'", onclick_code).groups()[0]
    resp = get_page_with_retry(session, popup_url, cookie, 3)
    # now resp is at the page saying it takes a few minuets to load
    # we grab the url to the final page
    next_page_url = list(resp.html.links)[0]
    wait(3)
    resp = get_page_with_retry(session, next_page_url, cookie, 5, 3)
    # finally we have the download path
    download_link = list(resp.html.absolute_links)[0]
    return download_link


def save_gallary_zip(name, download_link):
    path = os.path.join(GALLARY_ROOT_DIR, f'{name}.zip')
    if USE_ARIA2: # max 5 connections, continue, quite
        valid_link = download_link.replace('"', '\\"')
        valid_path = path.replace('"', '\\"')
        os.system(f'aria2c -x3 -q -c "{valid_link}" -o "{valid_path}"')
    else:
        with open(path, 'bw') as fle:
            fle.write(requests.get(download_link).content)


def get_page_with_retry(session, link, cookie, maxtry, wait_interval=None):
    """Try to fetch page and return response, if failed, retry after 1 second."""
    count = 0
    while count < maxtry:
        try:
            return session.get(link, cookies=cookie)
        except requests.exceptions.ConnectionError:
            wait(wait_interval)
            count += 1
    raise Exception(f'Tried {maxtry} times and still cannot get page')


def at_non_exist_page(resp):
    """Return True if we are at the last page of favorites"""
    # if there is this td, we are at the last page, specifically
    # this is the greyed-out next-page button
    NOTICE = 'No unfiltered results in this page range. You either requested an invalid page or used too aggressive filters.'
    text = resp.html.text
    return re.search(NOTICE, text) is not None


def wait(length=WAIT_INTERVAL):
    """Wait for LENGTH or WAIT_INTERVAL seconds."""
    if length == None:
        length = WAIT_INTERVAL
    time.sleep(length)

# basically:
# - get favorite page
# - go through each page and grab links to each gallary
#   (that’s not downloaded yet)
# - go to each gallary, grab the archive download button’s link
# - get the download page, this page is the one asking you to wait for a few minutes
# - get the url to the result page from html
# - finally get the download url from this result page
#   (archive prepared, click link below to download)
if __name__ == '__main__':
    print("Start")
    cookie = None
    with open(COOKIE_FILE) as f1:
        cookie = json.load(f1)

    # get first page
    session = HTMLSession()
    resp = get_page_with_retry(session, FAV_URL, cookie, 3)

    
    # get all favorite pages and grab gallary links from them
    gallary_name_list = get_gallary_name_list(GALLARY_ROOT_DIR)
    gallary_link_list = []
    new_gallary_name_list = []
    page_idx = 0
    print(f'Found {len(gallary_name_list)} existing gallaries')
    print('Scanning gallaries')
    while not at_non_exist_page(resp):
        wait()
        new_link_list, new_name_list = get_gallary_link_and_name(resp, gallary_name_list)
        gallary_link_list += new_link_list
        new_gallary_name_list += new_name_list
        page_idx += 1
        next_page_url = f'{FAV_URL}?page={page_idx}'
        resp = get_page_with_retry(session, next_page_url, cookie, 3)
    print(f'Found {len(gallary_link_list)} new gallaries:')
    for name in new_gallary_name_list:
        print(f'  {name}')

        
    print('Start to download')
    # goes into each page and get download link
    total_gallary_count = len(gallary_link_list)
    current_count = 0
    failed_list = []
    # why use name from gallary_name_list rather than from archive
    # download? those names doesn’t always match! If I use gallary
    # names to test if I’ve downloaded the gallary and use archive names
    # to download, those gallaries appear as not-yet-downlaoded
    # gallaries every time.
    for gallary_link, gallary_name in zip(gallary_link_list, new_gallary_name_list):
        wait()
        try:
            current_count += 1
            print(f'Downloading gallary {current_count}/{total_gallary_count}')
            print(f'{gallary_name}')
            resp = get_page_with_retry(session, gallary_link, cookie, 5)
            wait()
            download_link = get_download_link(session, resp, cookie)
            wait()
            save_gallary_zip(gallary_name, download_link)
        except:
            failed_list.append((gallary_name, gallary_link))
    # print failed ones
    if failed_list != []:
        print(f'Failed to download {len(failed_list)} gallar(ies):')
        for name, link in failed_list:
            print(name)
            print(f'  {link}')
