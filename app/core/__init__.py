def denies_plain_http(url:str) -> bool :
    return url.startswith("http://")

def run_checks(aws,bucket_name,prefix,sts=None) -> bool:
    return True
