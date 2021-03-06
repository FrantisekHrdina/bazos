#!/usr/bin/env python3

import datetime
import os
import re
import sys
import time
import bs4 as bs4
import requests
import argparse
import configparser
import logging

# email sending
import pickle
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from base64 import urlsafe_b64encode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def save_current_ads(filename, ads):
    with open(filename, 'w', encoding='utf-8') as f:
        for ad in ads:
            f.write('{0};{1};{2}\n'.format(ad[0], ad[1], ad[2]))


def load_previous_ads_url(filename):
    urls = []
    if not os.path.isfile(filename):
        return urls

    with open(filename, 'r') as f:
        lines = f.readlines()
        for line in lines:
            splitted_line = line.split(';')
            url = splitted_line[0]
            urls.append(url)

    return urls


def find_new_ads(previous_ads_urls, ads):
    new_ads = []
    for ad in ads:
        if ad[0] not in previous_ads_urls:
            new_ads.append(ad)

    return new_ads


def gmail_authenticate(config):
    creds = None

    if os.path.exists(config['EMAIL']['TOKEN_FILENAME']):
        with open(config['EMAIL']['TOKEN_FILENAME'], 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(config['EMAIL']['CREDENTIALS_FILENAME'], config['EMAIL']['GMAIL_API'])
            creds = flow.run_local_server(port=0)
        with open(config['EMAIL']['TOKEN_FILENAME'], 'wb') as token:
            pickle.dump(creds, token)
    return build('gmail', 'v1', credentials=creds)


def send_email(keyword, new_ads, config, logging):
    if len(new_ads) == 0:
        logging.info('No new ads found')
        return

    logging.info('New ads found: {0}'.format(len(new_ads)))

    service = gmail_authenticate(config)

    message = MIMEMultipart()
    message['to'] = ' ,'.join(config[keyword]['RECIPIENTS'].split(' '))
    message['to'] = 'franta.hrdina@gmail.com'
    message['from'] = config['EMAIL']['SENDER']
    message['subject'] = 'Bazo?? hl??da??: {0}'.format(config[keyword]['TITLE'])
    generated_body = generate_body(new_ads, keyword, message['subject'])
    message.attach(MIMEText(generated_body, 'html'))

    encoded_body = {'raw': urlsafe_b64encode(message.as_bytes()).decode()}

    try:
        service.users().messages().send(
            userId='me',
            body=encoded_body
        ).execute()
        logging.info("Sending email successful")
    except Exception as exp:
        logging.error("Sending failed: {0}".format(repr(exp)))


def generate_body(new_ads, keyword, subject):
    body = ''

    body += '<h3>{0}</h3>\n'.format(subject)
    timestamp = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    body += '<h4>{0}</h4>\n'.format(timestamp)
    body += "<h5>kl????ov?? slova: {0}</h5>\n".format(config[keyword]['KEYWORDS'])
    body += '<table style="border-collapse: collapse;">'

    for line in new_ads:
        body += '\n<tr style="border-style: solid;border-width: 1px;border-color: gray;">' \
                   '<td style="vertical-align: middle;"><a href="{0}">{1}</a></td>' \
                   '<td nowrap align="right" style="vertical-align: middle;">{2}</td></tr>'.\
            format(line[0], line[0].split('/')[-1], line[1].replace(' ', '&nbsp;'))

    body += '</table>'

    return body


def load_ads(keyword, config):
    params = '?hledat={0}&hlokalita={1}&humkreis={2}&cenaod={3}&cenado={4}&order='.format(
        config[keyword]['KEYWORDS'], 
        config[keyword]['LOCATION'],
        config[keyword]['RADIUS'], 
        config[keyword]['MINIMUM_PRIZE'], 
        config[keyword]['MAXIMUM_PRIZE']
        )
    
    global_search = True if config[keyword]['URL'] == 'https://www.bazos.cz/' else False

    if global_search:
        url_string = config[keyword]['URL'] + 'search.php' + params
    else:
        url_string = config[keyword]['URL'] + params
    
    res = requests.get(url_string, verify=False)

    soup = bs4.BeautifulSoup(res.content, 'html.parser')

    total_re = re.compile(r".*Zobrazeno.* inzer??t?? z (.*).*")
    total = int(total_re.search(soup.text).group(1).replace(' ', '').strip())

    ads = []
    now = datetime.datetime.now()
    i = 0
    while i < total:
        # searching through global page must be solved diferently
        if global_search:
            tmp_res = requests.get(config[keyword]['URL'] + '/search.php' + params + '/&crz=' + str(i), verify=False)
        else:
            if i == 0:
                page = ''
            else:
                page = str(i) + '/'

            tmp_res = requests.get(config[keyword]['URL'] + page + params, verify=False)
        tmp_soup = bs4.BeautifulSoup(tmp_res.content, 'html.parser')

        tmp_ads = tmp_soup.find_all('div', class_='inzeraty')
        for ad in tmp_ads:
            prize = ad.find('div', class_='inzeratycena').text.strip()
            if global_search:
                ad_url = ad.find('h2', class_='nadpis').find('a')['href']
            else:
                ad_url = config[keyword]['ADS_URL'] + ad.find('h2', class_='nadpis').find('a')['href']

            date_span = ad.find('span', class_='velikost10').text
            date_regex = re.compile(r".*(\[.*\]).*")
            date_string = date_regex.search(date_span).group(1).replace(' ', '').strip()
            date_time = datetime.datetime.strptime(date_string.replace('[', '').replace(']', ''), '%d.%m.%Y')
            if now - date_time >= datetime.timedelta(days=2):
                break
            ads.append((ad_url, prize, date_time))

        if now - date_time >= datetime.timedelta(days=10):
            break

        time.sleep(15)
        i += 20
    return ads


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bazo?? hl??da??')
    parser.add_argument('--option', required=True, help='Select option, that you have configured in config.ini')
    parser.add_argument('--config', required=True, help='Path to config file')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config)
    logging.basicConfig(filename=config['GENERAL']['LOG'], format='%(asctime)s %(message)s', level=logging.DEBUG)
    logging.info('Bazo?? started')

    requests.packages.urllib3.disable_warnings()

    if args.option not in config.sections():
        logging.warning('Selected option not presented in configuration')
        sys.exit()

    logging.info('Option: {0}'.format(args.option))
    ads = load_ads(args.option, config)
    previous_ads_url = load_previous_ads_url(config[args.option]['FILENAME'])
    save_current_ads(config[args.option]['FILENAME'], ads)
    new_ads = find_new_ads(previous_ads_url, ads)
    send_email(args.option, new_ads, config, logging)

    logging.info('Bazo?? ended')
