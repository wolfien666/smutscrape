from datetime import datetime
date_str = "2017-09-03T17:49:03+00:00"
date_format = "%Y-%m-%dT%H:%M:%S%z"
parsed = datetime.strptime(date_str, date_format).strftime('%Y-%m-%d')
print(parsed)  # Outputs: 2017-09-03
