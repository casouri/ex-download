from requests_html import HTMLSession
import requests
import json
import os
import re
import time
import unicodedata

GALLERY_DIR = './gallery'
INFO_DIR = './info'

EX_URL = 'https://exhentai.org'
FAV_URL = 'https://exhentai.org/favorites.php'
# GALLERY_LINK_XPATH = '//div[@class = "gl1t"]/a/@href'
GALLERY_LINK_NODE_XPATH = '//div[@class = "gl1t"]/div/div/a'
DOWNLOAD_ARCHIVE_ONCLICK_XPATH = '//a[text() = "Archive Download"]/@onclick'

# Favorite label.
LABEL_XPATH = '//*[@id="favoritelink"]'
UPLOADER_XPATH = '//*[@id="gdn"]'
COMMENT_XPATH = '//*[@class="c1"]'
MISC_XPATH = '//*[@id="gdd"]'
TAGLIST_XPATH = '//*[@id="taglist"]'

### Helpers

def get_page_with_retry(session, link, cookie, maxtry):
    """Try to fetch page and return response.
If failed, retry after 1 second."""
    count = 0
    while True:
        if count == maxtry:
            return
        try:
            return session.get(link, cookies=cookie)
        except requests.exceptions.ConnectionError:
            time.sleep(1)
            count += 1
            continue

def at_non_exist_page(resp):
    """Return True if we are at the last page of favorites"""
    # If there is this td, we are at the last page, specifically
    # this is the greyed-out next-page button.
    NOTICE = 'No unfiltered results in this page range. You either requested an invalid page or used too aggressive filters.'
    text = resp.html.text
    return re.search(NOTICE, text) is not None

def make_filename(name):
    """Make NAME a valid UNIX filename."""
    return name.replace('/', ' ')

### Getting things

def gallery_link_in_page(response):
    """Get each gallery in RESPONSE and return them as a list.
Return a list of (LINK, NAME).
The page should be the page showing thumbnails of each gallery."""
    node_list = response.html.xpath(GALLERY_LINK_NODE_XPATH)
    lst = []
    for node in node_list:
        link = node.attrs['href']
        name = unicodedata.normalize('NFC', node.text)
        lst.append((link, name))
    return lst

def all_gallery_links(session, cookie):
    """Return a list of all gallery links."""
    lst = []
    page_idx = 0
    run = True
    while run:
        url = f'{FAV_URL}?page={page_idx}'
        resp = session.get(url, cookies=cookie)
        lst += gallery_link_in_page(resp)
        page_idx += 1
        run = not at_non_exist_page(resp)
    return lst

def downloaded_galleries(gallery_dir):
    """Get a list of gallery names under GALLERY_DIR.
I.e., ones that are already downloaded."""
    name_list = []
    for fl in os.listdir(gallery_dir):
        if os.path.isfile(os.path.join(gallery_dir, fl)):
            filename = os.path.splitext(os.path.basename(fl))[0]
            name_list.append(unicodedata.normalize('NFC', filename))
    return name_list

def download_link_in_gallery(session, resp, cookie):
    """Get download link from gallery page RESP.
If failed, return None."""
    # “Click” on the download link.
    onclick_code = resp.html.xpath(DOWNLOAD_ARCHIVE_ONCLICK_XPATH)[0]
    popup_url = re.search("'(https://.+)'", onclick_code).groups()[0]
    resp = session.get(popup_url, cookies=cookie)

    # Now RESP is at the page saying it takes a few minuets to load.
    # We grab the url to the final page.
    next_page_url = list(resp.html.links)[0]
    resp = get_page_with_retry(session, next_page_url, cookie, 5)

    # Finally we have the download path.
    # name_node_list = resp.html.xpath('//strong')
    download_link = list(resp.html.absolute_links)[0]
    return download_link

def info_in_gallery(resp):
    """Return information about the gallery.
RESP is the gallery page. Return a dictionary with these keywords:
misc, taglist, uploader, label, comment."""
    misc = resp.html.xpath(MISC_XPATH)[0].text
    taglist = resp.html.xpath(TAGLIST_XPATH)[0].text
    uploader = resp.html.xpath(UPLOADER_XPATH)[0].text
    label = resp.html.xpath(LABEL_XPATH)[0].text
    comment = "\n\n\n\n".join(map(lambda elm: elm.text,
                            resp.html.xpath(COMMENT_XPATH)))
    return {'misc': misc, 'taglist': taglist, 'uploader': uploader,
            'label': label, 'comment': comment}



### Main program

if __name__ == '__main__':
    if not os.path.exists(GALLERY_DIR):
        os.makedirs(GALLERY_DIR)
    if not os.path.exists(INFO_DIR):
        os.makedirs(INFO_DIR)

    cookie = None
    with open('cookie.json', 'r') as fle:
        cookie = json.load(fle)
    session = HTMLSession()

    # Get downloaded galleries.
    downloaded_gallery_list = downloaded_galleries(GALLERY_DIR)
    print(f'Found {len(downloaded_gallery_list)} galleries on drive')

    # Get galleries on exhentai.
    print('Scanning for galleries on exhentai...')
    gallery_link_list = all_gallery_links(session, cookie)
    print(f'Found {len(gallery_link_list)} galleries on exhentai')

    # Filter out new galleries.
    new_galleries = []
    for (link, name) in gallery_link_list:
        if not ((make_filename(name) in downloaded_gallery_list)):
            new_galleries.append((link, name))

    # List new galleries.
    print(f'{len(new_galleries)} of them are new galleries:')
    for (link, name) in new_galleries:
        print(f'  {name}')

    # Download galleries.
    failed_list = []
    idx = 1
    for (link, name) in new_galleries:
        try:
            print(f'Downloading gallery {idx}/{len(new_galleries)}')
            resp = get_page_with_retry(session, link, cookie, 5)
            filename = make_filename(name)

            info = info_in_gallery(resp)
            with open(os.path.join(INFO_DIR, f'{filename}.org'),
                          'w+') as fl:
                fl.write(f'| Uploader | {info["uploader"]} |\n')
                fl.write(f'| Label    | {info["label"]} |\n')
                fl.write('\n')
                fl.write(f'* Misc\n\n{info["misc"]}\n\n')
                fl.write(f'* Taglist\n\n{info["taglist"]}\n\n')
                fl.write(f'* Comment\n\n{info["comment"]}\n\n')

            download_link = download_link_in_gallery(session,
                                                     resp, cookie)
            with open(os.path.join(GALLERY_DIR, f'{filename}.zip'),
                      'bw') as fl:
                fl.write(requests.get(download_link).content)
            idx += 1

        except Exception as err:
            print('Failed to fetch download link from gallery:')
            print(err)
            failed_list.append((link, name))

    if len(failed_list) > 0:
        print(f'Failed to download {len(failed_list)} galleries:')

        for (link, name) in failed_list:
            print(name)
