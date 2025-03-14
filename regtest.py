from datetime import datetime
date_str = "2017-09-03T17:49:03+00:00"
date_format = "2006-01-02T15:04:05+00:00"
parsed = datetime.strptime(date_str, date_format).strftime('%Y-%m-%d')
print(parsed)  # Outputs: 2017-09-03
