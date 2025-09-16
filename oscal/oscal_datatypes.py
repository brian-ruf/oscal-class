OSCAL_DATATYPES = {
    "base64": {
        "base-type": "string",
        "xml-pattern": r"[0-9A-Za-z+/]+={0,2}",
        "json-pattern": r"^[0-9A-Za-z+/]+={0,2}$",
        "recommended-pattern": r"[0-9A-Za-z+/]+={0,2}",
        "documentation": "A trimmed string, at least one character with no leading or trailing whitespace.",
        "remarks": "",
        "links": [
            {
                "title": "RFC4648",
                "url": "https://www.rfc-editor.org/rfc/rfc4648"
            }
        ]
    },
    "boolean": {
        "base-type": "boolean",
        "xml-pattern": r"(true|false|1|0)",
        "json-pattern": r"^(true|false)$",
        "recommended-pattern": r"(true|false|1|0)",
        "editing-pattern": r"(true|false)",
        "documentation": "A boolean value: either true or false.",
        "remarks": "",
        "links": []
    },
    "date": {
        "base-type": "string",
        "xml-pattern": r"(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))(Z|[+-][0-9]{2}:[0-9]{2})?",
        "json-pattern": r"^(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))(Z|[+-][0-9]{2}:[0-9]{2})?$",
        "recommended-pattern": r"\d{4}-\d{2}-\d{2}",
        "documentation": "A string representing a 24-hour period, optionally qualified by a timezone. A date-with-timezone is formatted according to “full-date” as defined RFC3339, with the addition of an optional timezone, specified as a time-offset according to RFC3339.\n\nThis is the same as date-with-timezone, except the timezone portion is optional. This can be used to support formats that have ambiguous timezones for date values.",
        "remarks": "",
        "links": [
            {
                "title": "RFC 3339, Section 5.6",
                "url": "https://tools.ietf.org/html/rfc3339#section-5.6"
            }
        ]
    },
    "date-with-timezone": {
        "base-type": "string",
        "xml-pattern": r"(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))(Z|[+-][0-9]{2}:[0-9]{2})",
        "json-pattern": r"^(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))(Z|[+-][0-9]{2}:[0-9]{2})$",
        "recommended-pattern": r"\d{4}-\d{2}-\d{2}(((Z))|([-+][0-9]{2}:[0-9]{2}))",
        "documentation": "A string representing a 24-hour period in a given timezone. A date-with-timezone is formatted according to “full-date” as defined RFC3339, with the addition of a timezone, specified as a time-offset according to RFC3339.\n\nThis type requires that the time-offset (timezone) is always provided. This use of timezone ensure that date information exchanged across timezones is unambiguous.",
        "remarks": "",
        "links": [
            {
                "title": "RFC 3339, Section 5.6",
                "url": "https://tools.ietf.org/html/rfc3339#section-5.6"
            }
        ]
    },
    "date-time": {
        "base-type": "string",
        "xml-pattern": r"(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))T(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\.[0-9]+)?(Z|(-((0[0-9]|1[0-2]):00|0[39]:30)|\+((0[0-9]|1[0-4]):00|(0[34569]|10):30|(0[58]|12):45)))?",
        "json-pattern": r"^(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))T(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\\.[0-9]+)?(Z|(-((0[0-9]|1[0-2]):00|0[39]:30)|\\+((0[0-9]|1[0-4]):00|(0[34569]|10):30|(0[58]|12):45)))?$",
        "recommended-pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[-+]\d{2}:\d{2})",
        "documentation": "A string representing a point in time, optionally qualified by a timezone. This date and time value is formatted according to “date-time” as defined RFC3339, except the timezone (time-offset) is optional.\n\nThis is the same as date-time-with-timezone, except the timezone portion is optional. This can be used to support formats that have ambiguous timezones for date/time values.",
        "remarks": "",
        "links": [
            {
                "title": "RFC 3339, Section 5.6",
                "url": "https://tools.ietf.org/html/rfc3339#section-5.6"
            }
        ]
    },
    "date-time-with-timezone": {
        "base-type": "string",
        "xml-pattern": r"(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))T(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\.[0-9]+)?(Z|(-((0[0-9]|1[0-2]):00|0[39]:30)|\+((0[0-9]|1[0-4]):00|(0[34569]|10):30|(0[58]|12):45)))",
        "json-pattern": r"^(((2000|2400|2800|(19|2[0-9](0[48]|[2468][048]|[13579][26])))-02-29)|(((19|2[0-9])[0-9]{2})-02-(0[1-9]|1[0-9]|2[0-8]))|(((19|2[0-9])[0-9]{2})-(0[13578]|10|12)-(0[1-9]|[12][0-9]|3[01]))|(((19|2[0-9])[0-9]{2})-(0[469]|11)-(0[1-9]|[12][0-9]|30)))T(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\\.[0-9]+)?(Z|(-((0[0-9]|1[0-2]):00|0[39]:30)|\\+((0[0-9]|1[0-4]):00|(0[34569]|10):30|(0[58]|12):45)))$",
        "recommended-pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[-+]\d{2}:\d{2})",
        "documentation": "A string representing a point in time in a given timezone. This date and time value is formatted according to “date-time” as defined RFC3339\n\nThis type requires that the time-offset (timezone) is always provided. This use of timezone ensures that date/time information exchanged across timezones is unambiguous.",
        "remarks": "",
        "links": [
            {
                "title": "RFC 3339, Section 5.6",
                "url": "https://tools.ietf.org/html/rfc3339#section-5.6"
            }
        ]
    },
    "day-time-duration": {
        "base-type": "string",
        "xml-pattern": r"-?P([0-9]+D(T(([0-9]+H([0-9]+M)?(([0-9]+|[0-9]+(\.[0-9]+)?)S)?)|([0-9]+M(([0-9]+|[0-9]+(\.[0-9]+)?)S)?)|([0-9]+|[0-9]+(\.[0-9]+)?)S))?)|T(([0-9]+H([0-9]+M)?(([0-9]+|[0-9]+(\.[0-9]+)?)S)?)|([0-9]+M(([0-9]+|[0-9]+(\.[0-9]+)?)S)?)|([0-9]+|[0-9]+(\.[0-9]+)?)S)",
        "json-pattern": r"^-?P([0-9]+D(T(([0-9]+H([0-9]+M)?(([0-9]+|[0-9]+(\\.[0-9]+)?)S)?)|([0-9]+M(([0-9]+|[0-9]+(\\.[0-9]+)?)S)?)|([0-9]+|[0-9]+(\\.[0-9]+)?)S))?)|T(([0-9]+H([0-9]+M)?(([0-9]+|[0-9]+(\\.[0-9]+)?)S)?)|([0-9]+M(([0-9]+|[0-9]+(\\.[0-9]+)?)S)?)|([0-9]+|[0-9]+(\\.[0-9]+)?)S)$",
        "recommended-pattern": r"([+-]?)(\\d+)((?:\\.|e|E)\\d+)?",
        "documentation": "An amount of time quantified in days, hours, minutes, and seconds based on ISO-8601 durations (see also RFC3339 appendix A).",
        "remarks": "",
        "links": [
            {
                "title": "RFC 3339, Appendix A",
                "url": "https://tools.ietf.org/html/rfc3339#appendix-A"
            }
        ]
    },    
    "decimal": {
        "base-type": "number",
        "xml-pattern": r"\S(.*\S)?",
        "json-pattern": r"(\\+|-)?([0-9]+(\\.[0-9]*)?|\\.[0-9]+)",
        "recommended-pattern": r"([+-]?)(\\d+)((?:\\.|e|E)\\d+)?",
        "documentation": "A real number.",
        "remarks": "A real number expressed using a whole and optional fractional part separated by a period.",
        "links": []
    },
    "email-adress": {
        "base-type": "string",
        "xml-pattern": r"(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|\"(?:[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x21\\x23-\\x5b\\x5d-\\x7f]|\\\\[\\x01-\\x09\\x0b\\x0c\\x0e-\\x7f])*\")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x21-\\x5a\\x53-\\x7f]|\\\\[\\x01-\\x09\\x0b\\x0c\\x0e-\\x7f])+)\\])",
        "json-pattern": r"^(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|\"(?:[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x21\\x23-\\x5b\\x5d-\\x7f]|\\\\[\\x01-\\x09\\x0b\\x0c\\x0e-\\x7f])*\")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x21-\\x5a\\x53-\\x7f]|\\\\[\\x01-\\x09\\x0b\\x0c\\x0e-\\x7f])+)\\])$",
        "recommended-pattern": r".+@.+",
        "documentation": "An email address string formatted according to RFC6531.",
        "remarks": "This is a basic pattern for email validation. More complex validation should be done at runtime.",
        "links": [
            {
                "title": "RFC 6531",
                "url": "https://tools.ietf.org/html/rfc6531"
            }
        ]
    },
    "hostname": {
        "base-type": "string",
        "xml-pattern": r"",
        "json-pattern": r"^\\S(.*\\S)?$",
        "recommended-pattern": r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*",
        "documentation": "An internationalized Internet host name string formatted according to section 2.3.2.3 of RFC5890.",
        "remarks": "",
        "links": [
            {
                "title": "RFC 5890, Section 2.3.2.3",
                "url": "https://tools.ietf.org/html/rfc5890#section-2.3.2.3"
            }
        ]
    },
    "integer": {
        "base-type": "integer",
        "xml-pattern": r"[-+]?[0-9]+",
        "json-pattern": r"^[-+]?[0-9]+$",
        "recommended-pattern": r"[+-]?\d+",
        "documentation": "A whole number value.",
        "remarks": "",
        "links": []
    },
    "ipv4-address": {
        "base-type": "string",
        "xml-pattern": r"((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]).){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])",
        "json-pattern": r"^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]).){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])$",
        "recommended-pattern": r"((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])",
        "documentation": "An Internet Protocol version 4 address represented using dotted-quad syntax as defined in section 3.2 of RFC2673.",
        "remarks": "Example: 192.168.1.1",
        "links": [
            {
                "title": "RFC 2673, Section 3.2",
                "url": "https://tools.ietf.org/html/rfc2673#section-3.2"
            }
        ]
    },
    "ipv6-address": {
        "base-type": "string",
        "xml-pattern": r"(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|[fF][eE]80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::([fF]{4}(:0{1,4}){0,1}:){0,1}((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]).){3,3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]).){3,3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]))",
        "json-pattern": r"^(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|[fF][eE]80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::([fF]{4}(:0{1,4}){0,1}:){0,1}((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]).){3,3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]).){3,3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9]))$",
        "recommended-pattern": r"(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))",
        "documentation": "An Internet Protocol version 6 address represented using the syntax defined in section 2.2 of RFC3513.",
        "remarks": "Example: 2001:db8:85a3::8a2e:370:7334",
        "links": [
            {
                "title": "RFC 3513, Section 2.2",
                "url": "https://tools.ietf.org/html/rfc3513#section-2.2"
            }
        ]
    },
    "non-negative-integer": {
        "base-type": "integer",
        "xml-pattern": r"\S(.*\S)?",
        "json-pattern": r"",
        "recommended-pattern": r"\d+",
        "documentation": "An integer value that is equal to or greater than 0.",
        "remarks": "",
        "links": []
    },
    "positive-integer": {
        "base-type": "integer",
        "xml-pattern": r"\S(.*\S)?",
        "json-pattern": r"",
        "recommended-pattern": r"[+]?[1-9]\d*",
        "documentation": "An integer value that is greater than 0.",
        "remarks": "",
        "links": []
    },
    "string": {
        "base-type": "string",
        "xml-pattern": r"\S(.*\S)?",
        "json-pattern": r"^\\S(.*\\S)?$",
        "recommended-pattern": r".*",
        "documentation": "A non-empty string of unicode characters with leading and trailing whitespace disallowed.\n\nWhitespace is: `U+9`, `U+10`, `U+32` or `[ \n\t]+`.",
        "remarks": "",
        "links": []
    },
    "token": {
        "base-type": "string",
        "xml-pattern": r"(\p{L}|_)(\p{L}|\p{N}|[.\-_])*",
        "json-pattern": r"^(\\p{L}|_)(\\p{L}|\\p{N}|[.\\-_])*$",
        "recommended-pattern": r"(\p{L}|_)(\p{L}|\p{N}|[.\-_])*",
        "documentation": "A non-colonized name as defined by XML Schema Part 2: Datatypes Second Edition.",
        "remarks": "",
        "links": [
            {
                "title": "XML Schema Part 2: Datatypes Second Edition",
                "url": "https://www.w3.org/TR/xmlschema11-2/#NCName"
            }
        ]
    },
    "uri": {
        "base-type": "string",
        "xml-pattern": r"[\S]+",
        "json-pattern": r"^[\S]+$",
        "recommended-pattern": r"\S+",
        "documentation": "A Universal Resource Identifier (URI) formatted according to RFC3986.",
        "remarks": "Requires a scheme with colon per RFC3986.",
        "links": [
            {
                "title": "RFC 3986",
                "url": "https://tools.ietf.org/html/rfc3986"
            }
        ]
    },
    "uri-reference": {
        "base-type": "string",
        "xml-pattern": r"[\S]+",
        "json-pattern": r"^[\S]+$",
        "recommended-pattern": r"\S+",
        "documentation": "A URI Reference, either a URI or a relative-reference, formatted according to section 4.1 of RFC3986.",
        "remarks": "A trimmed URI having at least one character with no leading or trailing whitespace.",
        "links": [
            {
                "title": "RFC 3986, Section 4.1",
                "url": "https://tools.ietf.org/html/rfc3986#section-4.1"
            }
        ]
    },
    "uuid": {
        "base-type": "string",
        "xml-pattern": r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}",
        "json-pattern": r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$",
        "recommended-pattern": r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}",
        "documentation": "A version 4 or 5 Universally Unique Identifier (UUID) as defined by RFC4122.",
        "remarks": "Example: bbf21f44-7702-43fa-abfa-fba687ecbfb7",
        "links": [
            {
                "title": "RFC 4122",
                "url": "https://tools.ietf.org/html/rfc4122"
            }
        ]
    },
    "year-month-duration": {
        "base-type": "string",
        "xml-pattern": r"-?P([0-9]+Y)?([0-9]+M)?",
        "json-pattern": r"^-?P([0-9]+Y)?([0-9]+M)?$",
        "recommended-pattern": r"([+-]?)(\\d+)((?:\\.|e|E)\\d+)?",
        "documentation": "An amount of time quantified in years and months based on ISO-8601 durations (see also RFC3339 appendix A).",
        "remarks": "",
        "links": [
            {
                "title": "ISO 8601",
                "url": "https://en.wikipedia.org/wiki/ISO_8601#Durations"
            },
            {
                "title": "RFC 3339, Appendix A",
                "url": "https://tools.ietf.org/html/rfc3339#appendix-A"
            }
        ]
    },
    "markup-line": {
        "base-type": "string",
        "xml-pattern": r"",
        "json-pattern": r"",
        "recommended-pattern": r"",
        "documentation": "Structured prose text is designed to map cleanly to equivalent subsets of HTML and Markdown. \n\nThe markup-line type is a string that contains a single line of text. The text may contain markup, but it is not required to do so.",
        "remarks": "",
        "links": [
            {
                "title": "NIST Metaschema Markup Line",
                "url": "https://pages.nist.gov/metaschema/specification/datatypes/#markup-line"
            }
        ]
    },
    "markup-multiline": {
        "base-type": "string",
        "xml-pattern": r"",
        "json-pattern": r"",
        "recommended-pattern": r"",
        "documentation": "Structured prose text is designed to map cleanly to equivalent subsets of HTML and Markdown. \n\nThe markup-multiline type is a string that may contain multiple lines of text as well as block formatting. The text may contain markup, but it is not required to do so.",
        "remarks": "",
        "links": [
            {
                "title": "NIST Metaschema Markup Multiline",
                "url": "https://pages.nist.gov/metaschema/specification/datatypes/#markup-multiline"
            }
        ]
    }
}
