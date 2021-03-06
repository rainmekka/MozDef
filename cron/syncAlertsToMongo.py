#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# Copyright (c) 2014 Mozilla Corporation

import calendar
import logging
import random
import sys
from datetime import datetime
from configlib import getConfig, OptionParser
from logging.handlers import SysLogHandler
from pymongo import MongoClient

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lib'))
from utilities.toUTC import toUTC
from elasticsearch_client import ElasticsearchClient
from query_models import SearchQuery, TermMatch

logger = logging.getLogger(sys.argv[0])


def loggerTimeStamp(self, record, datefmt=None):
    return toUTC(datetime.now()).isoformat()


def initLogger():
    logger.level = logging.INFO
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    formatter.formatTime = loggerTimeStamp
    if options.output == 'syslog':
        logger.addHandler(
            SysLogHandler(
                address=(options.sysloghostname, options.syslogport)))
    else:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formatter)
        logger.addHandler(sh)


def genMeteorID():
    return('%024x' % random.randrange(16**24))


def getESAlerts(es):
    search_query = SearchQuery(minutes=50)
    search_query.add_must(TermMatch('_type', 'alert'))
    results = search_query.execute(es, indices=['alerts'], size=10000)
    return results


def ensureIndexes(mozdefdb):
    '''
    make sure we've got or create
    1) an index on the utcepoch field in descending order
       to make it easy on the alerts screen queries.
    2) an index on esmetadata.id for correlation to ES

    '''
    alerts = mozdefdb['alerts']
    alerts.ensure_index([('utcepoch',-1)])
    alerts.ensure_index([('esmetadata.id',1)])


def updateMongo(mozdefdb, esAlerts):
    alerts = mozdefdb['alerts']
    for a in esAlerts['hits']:
        # insert alert into mongo if we don't already have it
        alertrecord = alerts.find_one({'esmetadata.id': a['_id']})
        if alertrecord is None:
            # new record
            mrecord = a['_source']
            # generate a meteor-compatible ID
            mrecord['_id'] = genMeteorID()
            # capture the elastic search meta data (index/id/doctype)
            # set the date back to a datetime from unicode, so mongo/meteor can properly sort, select.
            mrecord['utctimestamp']=toUTC(mrecord['utctimestamp'])
            # also set an epoch time field so minimongo can sort
            mrecord['utcepoch'] = calendar.timegm(mrecord['utctimestamp'].utctimetuple())
            mrecord['esmetadata'] = dict()
            mrecord['esmetadata']['id'] = a['_id']
            mrecord['esmetadata']['index'] = a['_index']
            mrecord['esmetadata']['type'] = a['_type']
            alerts.insert(mrecord)


def main():
    logger.debug('starting')
    logger.debug(options)
    try:
        es = ElasticsearchClient((list('{0}'.format(s) for s in options.esservers)))
        client = MongoClient(options.mongohost, options.mongoport)
        mozdefdb = client.meteor
        ensureIndexes(mozdefdb)
        esResults = getESAlerts(es)
        updateMongo(mozdefdb, esResults)

    except Exception as e:
        logger.error("Exception %r sending health to mongo" % e)


def initConfig():
    # output our log to stdout or syslog
    options.output = getConfig('output', 'stdout', options.configfile)
    # syslog hostname
    options.sysloghostname = getConfig('sysloghostname',
                                       'localhost',
                                       options.configfile)
    # syslog port
    options.syslogport = getConfig('syslogport', 514, options.configfile)

    # elastic search server settings
    options.esservers = list(getConfig('esservers',
                                       'http://localhost:9200',
                                       options.configfile).split(','))
    options.mongohost = getConfig('mongohost', 'localhost', options.configfile)
    options.mongoport = getConfig('mongoport', 3001, options.configfile)


if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option(
        "-c",
        dest='configfile',
        default=sys.argv[0].replace('.py', '.conf'),
        help="configuration file to use")
    (options, args) = parser.parse_args()
    initConfig()
    initLogger()
    main()
