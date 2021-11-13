#!/usr/bin/env python3

import datetime
import os
import re
import smtplib
import sys
import time
import bs4 as bs4
import requests
import argparse
import configparser
from email.header import Header
import logging


def save_current_ads(filename, inzeraty):
    with open(filename, 'w', encoding='utf-8') as f:
        for inzerat in inzeraty:
            f.write('{0};{1};{2}\n'.format(inzerat[0], inzerat[1], inzerat[2]))


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


def find_new_ads(previous_ads_url, ads):
    new_ads = []
    for ad in ads:
        if ad[0] not in previous_ads_url:
            new_ads.append(ad)

    return new_ads


def send_email(keyword, content, config, logging):
    if len(content) == 0:
        logging.info('No new ads found')
        return

    logging.info('New ads found: {0}'.format(len(content)))
    # Replace end sequence chars in subject
    subject = 'Bazoš hlídač: {0}'.format(config[keyword]['TITLE'])

    subject_header = Header(subject, 'utf-8').encode()
    #for item in ["\n", "\r"]:
    #    subject = subject.replace(item, ' ')

    recipients = config[keyword]['RECIPIENTS'].split(' ')

    headers = {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Disposition': 'inline',
        'Content-Transfer-Encoding': '8bit',
        'From': 'bazos-hlidac@gmail.com',
        'To': recipients,
        'Date': datetime.datetime.now().strftime('%a, %d %b %Y  %H:%M:%S %Z'),
        'X-Mailer': 'python',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:68.0) Gecko/20100101 Thunderbird/68.7.0',
        'Subject': subject_header
    }

    # create the message
    message = ''
    for key, value in headers.items():
        message += "%s: %s\n" % (key, value)

    message += "\n"
    message += '<h3>{0}</h3>\n'.format(subject)
    timestamp = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    message += '<h4>{0}</h4>\n'.format(timestamp)
    message += "<h5>klíčová slova: {0}</h5>\n".format(config[keyword]['KEYWORDS'])
    message += '<table>'

    for line in content:
        message += '\n<tr><td><a href="{0}">{1}</a></td><td align="right">{2}</td></tr>'.format(line[0], line[0].split('/')[-1], line[1])

    message += '</table>'
    # add contents
    #message += "\n%s\n" % (content)

    s = smtplib.SMTP(config['EMAIL']['SERVER'], config['EMAIL']['PORT'])

    s.ehlo()
    s.starttls()
    s.ehlo()

    s.login(config['EMAIL']['LOGIN'], config['EMAIL']['PASSWORD'])

    try:
        logging.info('Sending {0} to {1}'.format(subject, headers['To']))
        s.sendmail(headers['From'], headers['To'], message.encode("utf8"))
        logging.info("Sending email successful")
    except Exception as exp:
        logging.error("Sending failed: {0}".format(exp.mes))


def load_ads(keyword, config):
    params = '?hledat={0}&hlokalita={1}&humkreis={2}&cenaod={3}&cenado={4}&order='.format(
        config[keyword]['KEYWORDS'], 
        config[keyword]['LOCATION'],
        config[keyword]['RADIUS'], 
        config[keyword]['MINIMUM_PRIZE'], 
        config[keyword]['MAXIMUM_PRIZE']
        )
    
    global_search = True if config[keyword]['URL'] == 'https://www.bazos.cz/' else False

    #return
    if global_search:
        url_string = config[keyword]['URL'] + 'search.php' + params
    else:
        url_string = config[keyword]['URL'] + params
    
    res = requests.get(url_string, verify=False)

    soup = bs4.BeautifulSoup(res.content, 'html.parser')

    total_re = re.compile(r".*Zobrazeno.* inzerátů z (.*).*")
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

            datum_text = ad.find('span', class_='velikost10').text
            text_re = re.compile(r".*(\[.*\]).*")
            text = text_re.search(datum_text).group(1).replace(' ', '').strip()
            date_time = datetime.datetime.strptime(text.replace('[', '').replace(']', ''), '%d.%m.%Y')
            if now - date_time >= datetime.timedelta(days=2):
                break
            ads.append((ad_url, prize, date_time))

        if now - date_time >= datetime.timedelta(days=10):
            break

        time.sleep(15)
        i += 20
    return ads


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bazoš hlídač')
    parser.add_argument('--option', required=True, help='Select option, that you have configured in config.ini')
    parser.add_argument('--config', required=True, help='Path to config file')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config)
    logging.basicConfig(filename=config['GENERAL']['LOG'], format='%(asctime)s %(message)s', level=logging.DEBUG)
    logging.info('Bazoš started')

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

    logging.info('Bazoš ended')

