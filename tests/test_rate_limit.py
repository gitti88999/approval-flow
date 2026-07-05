import concurrent.futures
import logging
import requests

# Configure clean logging output for our local test runner
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Target server URL pointing to our Docker Compose ingestion port
URL = "http://ingestion-service-dapr:8000/submit"

# Baseline compliant payload matched to the structural schema expectations
BASE_PAYLOAD = {
    "id": "INV-LOAD-BASE",
    "submitter": "dana.cohen@northwind.example",
    "department": "engineering-2026Q2",
    "vendor": "Bistro 19",
    "vendorKnown": True,
    "invoiceNumber": "NW-INV-7781",
    "currency": "USD",
    "category": "meals",
    "attendees": 1,
    "lineItems": [
        {
            "description": "Team lunch",
            "quantity": 1,
            "unitPrice": 38.89
        }
    ],
    "taxAmount": 3.11,
    "total": 42.0,
    "receiptPresent": True,
    "date": "2026-05-12",
    "notes": "Solo working lunch rate-limiting test execution."
}

def send_invoice_request(index: int):
    """
    Modifies identifiers on the baseline payload dynamically per thread 
    to bypass the static GLOBAL-DUP signature filter.
    """
    # Create a deep copy of the base dictionary structure
    payload = BASE_PAYLOAD.copy()
    
    # Mutate values uniquely so each request looks like a brand-new transaction
    payload["id"] = f"INV-TEST-LMT-{index}"
    payload["invoiceNumber"] = f"NW-INV-7781-IDX-{index}"
    
    try:
        response = requests.post(URL, json=payload, timeout=3.0)
        
        # Log results clearly to pinpoint the exact moment of the 429 switch
        if response.status_code == 202:
            logger.info(f"Request #{index:02d}: Status 202 [Accepted] - Enqueued successfully.")
        elif response.status_code == 429:
            logger.warning(f"Request #{index:02d}: Status 429 [Too Many Requests] - RATE LIMIT BLOCKED!")
        else:
            logger.error(f"Request #{index:02d}: Unexpected Status {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as err:
        logger.error(f"Request #{index:02d} failed due to network exception: {str(err)}")

def execute_load_test():
    total_requests = 75
    concurrent_threads = 12
    
    logger.info(f"Initializing rate-limit penetration test: Sending {total_requests} requests using {concurrent_threads} concurrent workers...")
    
    # Fire off requests in parallel to simulate high burst traffic
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_threads) as executor:
        executor.map(send_invoice_request, range(1, total_requests + 1))

if __name__ == "__main__":
    execute_load_test()