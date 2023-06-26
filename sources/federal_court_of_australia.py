import urllib3
import certifi
import math
import os
import re
import inscriptis
import lxml
import orjsonl
from contextlib import suppress, nullcontext

_DECISIONS_PER_PAGE = 20
_INSCRIPTIS_CONFIG = inscriptis.model.config.ParserConfig(inscriptis.css_profiles.CSS_PROFILES['strict'])
_BASE_URL = 'https://search2.fedcourt.gov.au/s/search.html?collection=judgments&sort=adate&meta_v_phrase_orsand=judgments/Judgments&'

_session = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())

def get_searches():
    searches = orjsonl.load('indices/federal_court_of_australia/searches.jsonl') if os.path.exists('indices/federal_court_of_australia/searches.jsonl') else []

    # NOTE There is a bug that causes the total number of decisions reported by the first 11,000 or so Search Engine Results Pages (SERPs) to be lower than what it really is (cf https://search2.fedcourt.gov.au/s/search.html?collection=judgments&sort=adate&meta_v_phrase_orsand=judgments/Judgments&num_ranks=20&start_rank=1001 and https://search2.fedcourt.gov.au/s/search.html?collection=judgments&sort=adate&meta_v_phrase_orsand=judgments/Judgments&num_ranks=20&start_rank=66001). To determine the actual total number of decisions, we must extract it from what is supposed to be the final SERP.
    first_serp = _session.request('GET', f'{_BASE_URL}num_ranks=1').data.decode('utf-8')
    supposed_total_decisions = int(first_serp.split('1 of ')[1].split(' ')[0].replace(',', ''))

    supposed_final_serp = _session.request('GET', f'{_BASE_URL}num_ranks=1&start_rank={supposed_total_decisions}').data.decode('utf-8')
    total_decisions = int(supposed_final_serp.split(f'{"{:,}".format(supposed_total_decisions)} of ')[1].split(' ')[0].replace(',', ''))

    return [['federal_court_of_australia', serp_url] for i in range(0, math.ceil(total_decisions/_DECISIONS_PER_PAGE)) if (serp_url:=f'{_BASE_URL}num_ranks={_DECISIONS_PER_PAGE}&start_rank={i*_DECISIONS_PER_PAGE+1}') not in searches]

# NOTE There is a bug that causes certain SERPs to return the exact same results, thereby leading to the inclusion of duplicates in the document index.
def get_search(serp_url, lock=nullcontext()):
    # NOTE For whatever reason, some SERPs simply do not work. In those cases, we will return an empty list.
    try:
        documents = [['federal_court_of_australia', document_url] for document_url in re.findall(r'<a href="(https:\/\/www\.judgments\.fedcourt\.gov\.au\/judgments\/Judgments\/[^"\.]*)"', _session.request('GET', serp_url).data.decode('utf-8'))] # NOTE This regex excludes PDF decisions.
    except urllib3.exceptions.MaxRetryError:
        documents = []

    with lock:
        if documents:
            orjsonl.append('indices/federal_court_of_australia/documents.jsonl', documents)

        orjsonl.append('indices/federal_court_of_australia/searches.jsonl', [serp_url])

def get_document(url, lock=nullcontext()):
    try:
        # Ignore incorrectly encoded decisions (see, eg, https://www.judgments.fedcourt.gov.au/judgments/Judgments/fca/full/2010/2010fcafc0106) and PDF files that were not excluded from the document index due to the fact they do not end in '.pdf' (ie, https://www.judgments.fedcourt.gov.au/judgments/Judgments/tribunals/adfdat/1992/1992ADFDAT01).
        with suppress(UnicodeDecodeError):
            document = {
                'text' : inscriptis.Inscriptis(lxml.html.document_fromstring(_session.request('GET', url).data.decode('windows-1250')).xpath('//div[@class="judgment_content"]')[0], _INSCRIPTIS_CONFIG).get_text(),
                'type' : 'decision',
                'source' : 'federal_court_of_australia',
                'url' : url
            }

            with lock: orjsonl.append('corpus.jsonl', [document])

        with lock: orjsonl.append('indices/downloaded.jsonl', [['federal_court_of_australia', url]])
    except Exception as e:
        raise Exception(f'Error getting document from {url}.') from e