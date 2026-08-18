# USGS

Public **USGS-NWIS** queries use Water Data for the Nation.

- Modern: [OGC API](https://api.waterdata.usgs.gov/docs/ogcapi/) — `api.waterdata.usgs.gov`
- Legacy: `waterservices.usgs.gov` IV/DV when the DataID still has a **numeric** methodID

## API key

Optional but recommended. Without a key the OGC API is about **100 requests/hour per IP**. A key (api.data.gov) raises that.

1. Request a key: https://api.waterdata.usgs.gov/signup/
2. Key docs: https://api.waterdata.usgs.gov/docs/ogcapi/keys/
3. Paste it in **Options → USGS**. Stored in the OS keyring as `DataDoctor` / `usgsApiKey` and sent as `X-Api-Key`.

Other limits (as of 2026): 50,000 records per page (the app follows `rel=next`); continuous requests are chunked at 1,000 days (API cap ~1,100).

## Finding a DataID

Browse stations and parameters:

- [National Water Dashboard](https://dashboard.waterdata.usgs.gov/app/nwd/en/)
- [OGC API docs](https://api.waterdata.usgs.gov/docs/ogcapi/)
- Latest values for a site (lists `time_series_id`):  
  `https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items?f=json&monitoring_location_id=USGS-09428500`
- Continuous collection: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items`
- Daily collection: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items`

Data Doctor accepts:

| Form | Example | Notes |
|------|---------|--------|
| `Site-time_series_id-Parameter` | `09428500-14eef6ee402b4c50a7341a0efccf0cd4-00065` | Preferred full form |
| `Site-time_series_id` | `09428500-14eef6ee402b4c50a7341a0efccf0cd4` | Parameter optional; tsid is enough |
| `Site-Parameter` | `09428500-00065` | Looks up tsid; you may be prompted if several match |
| `Site-methodID-Parameter` | `09428500-158041-00065` | Legacy numeric methodID → old IV/DV services |

The **32-character hex** is the modern `time_series_id`. Store **that** hex in the data dictionary `dataID` column so labels and `precisionOverride` match.

Routing is automatic from the method segment: hex → OGC API; digits → legacy IV/DV.

The Query window’s DataID **info** button / picker can resolve `Site-Parameter`.

## Intervals

OGC collections used here are **continuous** (HOUR / INSTANT) and **daily** (DAY) only. There is **no monthly or yearly** product on this API — those interval choices are hidden when USGS-NWIS is selected. Default interval is `INSTANT:15`.

## Dictionary headers

A real `commonName` hit shows:

```
commonName-datatype
USGS
```

See [Data Dictionary](Data-Dictionary).
