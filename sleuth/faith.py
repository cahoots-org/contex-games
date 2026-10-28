"""Words the town never has: faith and gore."""

import re

FAITH = re.compile(
    r"\b(church\w*|chapel\w*|priest\w*|pious|pray\w*|sermon\w*|religio\w*|cults?|creed\w*|preach\w*|methodist\w*|"
    r"baptist\w*|catholic\w*|lutheran\w*|presbyterian\w*|episcopal\w*|evangelic\w*|parsonage\w*|rector\w*|vicar\w*|"
    r"pastors?|reverend\w*|parish\w*|dioces\w*|bishops?|clergy\w*|mosques?|synagogues?|temples?|rabbis?|imams?|"
    r"monks?|nuns?|bibl\w*|gospel\w*|hymn\w*|worship\w*|congregation\w*|deacon\w*|holy|gods?|goddess\w*|sabbath|"
    r"missionar\w*|seminar(?:y|ies))\b",
    re.IGNORECASE,
)
GORE = re.compile(
    r"\b(blood\w*|gor(e|y)|stab\w*|corpses?|knife|knives|guns?|shot|shoot\w*|strangl\w*|poison\w*|weapons?|"
    r"slaughter\w*|butcher\w*)\b",
    re.I,
)
