"""Offline multilingual query expansion for the bundled Indian Act library.

This module only adds search vocabulary and Act hints. It never generates legal
answers or substitutes for the text retrieved from the indexed PDFs.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable


def normalize_query_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    # Python's ``\w`` excludes many combining vowel marks used by Indic
    # scripts. Treating those marks as separators breaks words such as Telugu
    # ``సివిల్`` into fragments and causes false alias matches (for example,
    # a substring of ``వివరాలు`` can look like the standalone word ``విల్``).
    value = "".join(
        char if unicodedata.category(char)[0] in {"L", "M", "N"} or char == "_" else " "
        for char in value
    )
    return " ".join(value.split())


# Each row links ordinary English/Hindi/Telugu wording to English retrieval
# terms found in the Acts. Several rows point to more than one Act where the
# topic naturally spans those statutes.
_TOPICS: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], ...] = (
    ("contract", ("indian contract",), (
        "valid contract", "agreement", "contractor", "advance payment", "breach of contract", "refund",
        "भारतीय संविदा", "भारतीय अनुबंध", "वैध अनुबंध", "समझौता", "संविदा", "अनुबंध", "ठेकेदार", "अग्रिम भुगतान", "पैसे लौटाने",
        "భారతీయ ఒప్పంద", "చెల్లుబాటు అయ్యే ఒప్పందం", "ఒప్పందం", "కాంట్రాక్టర్", "ముందుగానే డబ్బు", "అడ్వాన్స్", "డబ్బు తిరిగి ఇవ్వడం", "పని ఆపేసి",
    ), "Indian Contract Act agreements contracts offer acceptance consideration capacity consent lawful object breach performance damages advance payment"),
    ("cpc", ("code of civil procedure",), (
        "civil procedure", "civil suit", "file a civil case", "दीवानी प्रक्रिया", "दीवानी मुकदमा", "सिविल प्रक्रिया संहिता", "सिविल मुकदमा",
        "సివిల్ ప్రొసీజర్", "సివిల్ కేసు", "సివిల్ దావా",
    ), "Code of Civil Procedure civil suit institution plaint summons written statement issues hearing judgment decree execution"),
    ("limitation", ("limitation",), (
        "limitation period", "time limit for filing", "filing deadline", "time barred", "समय सीमा", "समय-सीमा", "मियाद", "मुकदमा दायर करने की समय",
        "కాలపరిమితి", "కాల పరిమితి", "గడువు", "కేసు దాఖలు చేయడానికి",
    ), "Limitation Act period limitation suit filing deadline accrual of right to sue schedule article condonation delay"),
    ("rti", ("right to information",), (
        "right to information", "information request", "request public records", "सूचना का अधिकार", "आरटीआई", "जानकारी मांग", "सूचना मांग", "आरटीआई अपील",
        "సమాచార హక్కు", "ఆర్టీఐ", "సమాచారం కోర", "సమాచార అభ్యర్థన", "ఆర్టీఐ అప్పీల్",
    ), "Right to Information Act application information public information officer request disclosure first appeal second appeal"),
    ("digital_evidence", ("bharatiya sakshya", "information technology"), (
        "electronic record", "digital evidence", "electronic evidence", "online identity theft", "cyber identity", "डिजिटल साक्ष्य", "इलेक्ट्रॉनिक साक्ष्य", "इलेक्ट्रॉनिक रिकॉर्ड", "ऑनलाइन पहचान की चोरी",
        "డిజిటల్ ఆధారాలు", "ఎలక్ట్రానిక్ సాక్ష్యాలు", "ఎలక్ట్రానిక్ రికార్డులు", "ఆన్‌లైన్ గుర్తింపు దొంగతనం",
    ), "Bharatiya Sakshya Adhiniyam electronic records evidence admissibility certificate section 61 62 63 Information Technology Act identity theft"),
    ("negotiable_instruments", ("negotiable instruments",), (
        "cheque returned unpaid", "bounced cheque", "cheque dishonour", "dishonoured cheque", "चेक वापस", "चेक बाउंस", "भुगतान के बिना लौटाए गए चेक", "अनादरित चेक", "परक्राम्य लिखत अधिनियम",
        "చెక్కు తిరిగి", "చెక్కు బౌన్స్", "చెల్లింపుకాకుండా తిరిగి వచ్చిన చెక్కు", "బ్యాంకు చెల్లించకుండా తిరిగి", "నెగోషియబుల్ ఇన్‌స్ట్రుమెంట్స్ చట్టం",
    ), "Negotiable Instruments Act cheque dishonour returned unpaid notice drawer payee section 138"),
    ("legal_services", ("legal services authorities",), (
        "legal aid", "free legal assistance", "विधिक सेवा प्राधिकरण", "विधिक सेवा प्राधिकरण अधिनियम", "कानूनी सहायता", "मुफ्त कानूनी सहायता",
        "లీగల్ సర్వీసెస్ అథారిటీస్", "లీగల్ సర్వీసెస్ అథారిటీస్ చట్టం", "న్యాయ సహాయం", "ఉచిత న్యాయ సహాయం", "న్యాయ సేవలు",
    ), "Legal Services Authorities Act legal aid free legal services eligibility legal services authority lok adalat"),
    ("motor_vehicles", ("motor vehicles",), (
        "road accident compensation", "motor accident", "vehicle accident", "सड़क दुर्घटना", "मोटर वाहन", "दुर्घटना मुआवजा", "दुर्घटना मुआवज़ा",
        "రోడ్డు ప్రమాదం", "మోటార్ వాహనం", "ప్రమాద పరిహారం", "రోడ్డు ప్రమాద పరిహారం",
    ), "Motor Vehicles Act road accident motor vehicle compensation claims tribunal insurer driver owner"),
    ("pocso", ("protection of children from sexual",), (
        "child sexual abuse", "sexual abuse of a child", "report child abuse", "बाल लैंगिक अपराधों से संरक्षण", "बाल यौन अपराध", "बाल यौन शोषण", "बच्चे के शोषण की सूचना", "पॉक्सो", "पोक्सो",
        "పిల్లలపై లైంగిక దుర్వినియోగం", "బాలల లైంగిక వేధింపులు", "పోక్సో", "పిల్లలపై నేరం నివేదించ",
    ), "Protection of Children from Sexual Offences POCSO reporting child special court police mandatory report"),
    ("disability", ("rights of persons with disabilities",), (
        "disability rights", "rights of persons with disabilities", "दिव्यांगजन अधिकार", "विकलांगों के अधिकार", "दिव्यांग अधिकार",
        "వికలాంగుల హక్కులు", "వికలాంగుల హక్కుల చట్టం", "దివ్యాంగుల హక్కులు", "దివ్యాంగుల హక్కుల చట్టం", "వైకల్యం హక్కులు",
    ), "Rights of Persons with Disabilities Act equality non-discrimination accessibility education employment benchmark disability"),
    ("senior_citizens", ("maintenance and welfare of parents",), (
        "support elderly parent", "maintenance of senior citizens", "elderly parents", "वृद्ध माता-पिता", "वरिष्ठ नागरिक", "भरण-पोषण", "बुजुर्ग माता पिता",
        "వృద్ధ తల్లిదండ్రులు", "సీనియర్ సిటిజన్లు", "భరణం", "తల్లిదండ్రులకు ఆర్థిక సహాయం", "పిల్లలు సహాయం చేయడం లేదు",
    ), "Maintenance and Welfare of Parents and Senior Citizens Act maintenance tribunal parents senior citizens children relatives"),
    ("workplace_harassment", ("sexual harassment of women at workplace",), (
        "workplace sexual harassment", "unwelcome conduct at work", "harassment at work", "कार्यस्थल पर यौन उत्पीड़न", "कार्यस्थल पर महिलाओं", "आंतरिक समिति",
        "పని ప్రదేశంలో లైంగిక వేధింపులు", "పని ప్రదేశంలో మహిళలపై", "కార్యాలయంలో మహిళలపై", "కార్యాలయంలో లైంగిక వేధింపులు", "పని ప్రదేశం", "అంతర్గత కమిటీ",
    ), "Sexual Harassment of Women at Workplace prevention prohibition redressal internal committee complaint inquiry"),
    ("consumer", ("consumer protection",), (
        "defective product", "seller refuses replacement", "consumer complaint", "उपभोक्ता संरक्षण", "खराब सामान", "दोषपूर्ण वस्तु", "उपभोक्ता शिकायत",
        "వినియోగదారుల రక్షణ", "లోపభూయిష్ట వస్తువు", "వస్తువు మార్చడానికి నిరాకరించ", "వినియోగదారుల ఫిర్యాదు",
    ), "Consumer Protection Act consumer rights defective goods deficiency in service complaint district commission redressal"),
    ("it_cyber", ("information technology",), (
        "identity theft", "fake online account", "cyber crime", "online impersonation", "पहचान की चोरी", "नकली ऑनलाइन खाता", "साइबर अपराध",
        "గుర్తింపు దొంగతనం", "నకిలీ ఆన్‌లైన్ ఖాతా", "సైబర్ నేరం", "మరొకరి వివరాలు ఉపయోగించ",
    ), "Information Technology Act identity theft cheating by personation computer resource electronic signature section 66C 66D"),
    ("data_protection", ("digital personal data protection",), (
        "personal data privacy", "use of personal information", "data protection", "व्यक्तिगत डेटा", "निजी जानकारी का उपयोग", "डेटा संरक्षण",
        "వ్యక్తిగత డేటా", "వ్యక్తిగత సమాచారం వినియోగం", "డేటా రక్షణ",
    ), "Digital Personal Data Protection Act personal data processing consent data fiduciary rights duties"),
    ("domestic_violence", ("domestic violence",), (
        "domestic abuse", "protection order", "घरेलू हिंसा", "घरेलू दुर्व्यवहार", "संरक्षण आदेश",
        "గృహ హింస", "గృహ వేధింపులు", "రక్షణ ఉత్తర్వు",
    ), "Protection of Women from Domestic Violence Act protection order residence order monetary relief protection officer"),
    ("property", ("transfer of property",), (
        "transfer property", "property sale", "property ownership", "संपत्ति हस्तांतरण", "जमीन का हस्तांतरण", "मकान संपत्ति",
        "ఆస్తి బదిలీ", "భూమి బదిలీ", "ఆస్తి విక్రయం", "ఆస్తి యాజమాన్యం",
    ), "Transfer of Property Act sale mortgage lease gift exchange transfer ownership immovable property"),
    ("stamp", ("indian stamp",), (
        "stamp duty", "stamp paper", "स्टाम्प शुल्क", "स्टांप शुल्क", "स्टाम्प पेपर",
        "స్టాంప్ డ్యూటీ", "స్టాంపు పేపర్", "స్టాంప్ పేపర్",
    ), "Indian Stamp Act stamp duty instrument chargeable admissibility impounding"),
    ("registration", ("registration act",), (
        "register property document", "document registration", "दस्तावेज पंजीकरण", "दस्तावेज़ पंजीकरण", "रजिस्ट्री",
        "పత్రం రిజిస్ట్రేషన్", "ఆస్తి రిజిస్ట్రేషన్", "దస్తావేజు నమోదు",
    ), "Registration Act registration of documents immovable property compulsory registration time presentation"),
    ("succession", ("indian succession",), (
        "inheritance", "will probate", "succession certificate", "विरासत", "उत्तराधिकार", "वसीयत", "प्रोबेट",
        "వారసత్వం", "విల్", "వీలునామా", "ప్రొబేట్",
    ), "Indian Succession Act succession inheritance will probate letters administration succession certificate"),
    ("hindu_succession", ("hindu succession",), (
        "hindu inheritance", "daughter inheritance rights", "हिंदू उत्तराधिकार", "हिंदू विरासत", "बेटी का उत्तराधिकार",
        "హిందూ వారసత్వం", "హిందూ వారసత్వ హక్కులు", "కుమార్తె వారసత్వ హక్కులు",
    ), "Hindu Succession Act intestate succession heirs daughter son coparcenary property"),
    ("guardianship", ("hindu minority and guardianship",), (
        "child guardian", "minor child custody", "बच्चे का अभिभावक", "नाबालिग की अभिरक्षा", "अभिभावक",
        "పిల్లల సంరక్షకుడు", "మైనర్ పిల్లల సంరక్షణ", "గార్డియన్",
    ), "Hindu Minority and Guardianship Act natural guardian welfare of minor custody"),
    ("special_marriage", ("special marriage",), (
        "civil marriage", "interfaith marriage registration", "विशेष विवाह", "अंतरधार्मिक विवाह", "विवाह पंजीकरण",
        "ప్రత్యేక వివాహం", "వివాహ నమోదు", "మతాంతర వివాహం",
    ), "Special Marriage Act solemnization marriage notice registration interfaith marriage objection"),
    ("dowry", ("dowry prohibition",), (
        "dowry demand", "dowry harassment", "दहेज मांग", "दहेज उत्पीड़न", "दहेज निषेध",
        "కట్నం డిమాండ్", "కట్న వేధింపులు", "వరకట్న నిషేధం",
    ), "Dowry Prohibition Act demand giving taking dowry penalty"),
    ("child_marriage", ("prohibition of child marriage",), (
        "underage marriage", "child marriage", "बाल विवाह", "कम उम्र की शादी",
        "బాల్య వివాహం", "చిన్న వయసు వివాహం", "మైనర్ వివాహం",
    ), "Prohibition of Child Marriage Act child marriage voidable injunction child marriage prohibition officer"),
    ("ndps", ("narcotic drugs",), (
        "narcotics", "illegal drugs", "drug possession", "नशीले पदार्थ", "मादक पदार्थ", "ड्रग्स रखना",
        "మత్తు పదార్థాలు", "మాదక ద్రవ్యాలు", "డ్రగ్స్ కలిగి ఉండటం",
    ), "Narcotic Drugs and Psychotropic Substances Act possession trafficking narcotic psychotropic substance search seizure"),
    ("drugs_cosmetics", ("drugs and cosmetics",), (
        "medicine quality", "cosmetic product", "drug licence", "दवा गुणवत्ता", "औषधि लाइसेंस", "कॉस्मेटिक",
        "మందుల నాణ్యత", "ఔషధ లైసెన్స్", "కాస్మెటిక్స్",
    ), "Drugs and Cosmetics Act drug manufacture sale licence standard misbranded adulterated cosmetics"),
    ("child_labour", ("child and adolescent labour",), (
        "child labour", "children working", "बाल श्रम", "बाल मजदूरी", "बच्चों से काम",
        "బాల కార్మికులు", "పిల్లలతో పని చేయించడం", "బాల కార్మికత్వం",
    ), "Child and Adolescent Labour Prohibition Regulation employment children adolescents hazardous occupations"),
    ("corruption", ("prevention of corruption",), (
        "bribe", "public servant corruption", "भ्रष्टाचार", "रिश्वत", "सरकारी अधिकारी रिश्वत",
        "అవినీతి", "లంచం", "ప్రభుత్వ అధికారి లంచం",
    ), "Prevention of Corruption Act public servant undue advantage bribe offence investigation"),
    ("human_rights", ("protection of human rights",), (
        "human rights violation", "human rights commission", "मानवाधिकार उल्लंघन", "मानवाधिकार आयोग",
        "మానవ హక్కుల ఉల్లంఘన", "మానవ హక్కుల కమిషన్",
    ), "Protection of Human Rights Act human rights commission inquiry complaints powers"),
    ("money_laundering", ("prevention of money laundering",), (
        "money laundering", "proceeds of crime", "धन शोधन", "मनी लॉन्ड्रिंग", "अपराध की आय",
        "మనీ లాండరింగ్", "నేర ఆదాయం", "అక్రమ ధన చలామణి",
    ), "Prevention of Money Laundering Act proceeds of crime attachment search seizure adjudicating authority"),
    ("food_security", ("national food security",), (
        "food ration entitlement", "food security", "राशन का अधिकार", "खाद्य सुरक्षा", "सार्वजनिक वितरण प्रणाली",
        "ఆహార భద్రత", "రేషన్ హక్కు", "ప్రజా పంపిణీ వ్యవస్థ",
    ), "National Food Security Act food grains eligible households public distribution ration entitlement"),
    ("transgender", ("transgender persons",), (
        "transgender rights", "gender identity discrimination", "ट्रांसजेंडर अधिकार", "लिंग पहचान भेदभाव",
        "ట్రాన్స్‌జెండర్ హక్కులు", "లింగ గుర్తింపు వివక్ష",
    ), "Transgender Persons Protection of Rights Act identity certificate discrimination welfare employment"),
    ("public_examinations", ("public examinations",), (
        "exam paper leak", "cheating in public exam", "परीक्षा पेपर लीक", "परीक्षा में नकल", "अनुचित साधन परीक्षा",
        "పరీక్ష పేపర్ లీక్", "పరీక్షల్లో మోసం", "అక్రమ మార్గాలు పరీక్ష",
    ), "Public Examinations Prevention of Unfair Means Act paper leak cheating unfair means organized crime"),
    ("sports_governance", ("national sports governance",), (
        "sports federation governance", "national sports body", "खेल महासंघ", "खेल शासन",
        "క్రీడా సమాఖ్య పాలన", "జాతీయ క్రీడా సంస్థ",
    ), "National Sports Governance Act sports bodies national sports board federation elections ethics"),
    ("merchant_shipping", ("merchant shipping",), (
        "merchant ship", "shipping vessel", "seafarer rights", "व्यापारी जहाज", "समुद्री जहाज", "नाविक अधिकार",
        "మర్చంట్ షిప్పింగ్", "వాణిజ్య నౌక", "నావికుల హక్కులు",
    ), "Merchant Shipping Act ship vessel seafarer registration safety maritime administration"),
    ("major_ports", ("major port authorities",), (
        "major port", "port authority", "बंदरगाह प्राधिकरण", "प्रमुख बंदरगाह",
        "మేజర్ పోర్ట్ అథారిటీ", "ప్రధాన ఓడరేవు", "పోర్ట్ అథారిటీ",
    ), "Major Port Authorities Act board port authority administration powers functions"),
    ("maritime_piracy", ("maritime anti piracy",), (
        "piracy at sea", "pirate ship", "समुद्री डकैती", "समुद्री लूट",
        "సముద్ర దొంగతనం", "సముద్ర దోపిడీ",
    ), "Maritime Anti-Piracy Act piracy high seas jurisdiction punishment"),
    ("aviation", ("bharatiya vayuyan",), (
        "aircraft aviation law", "aircraft operation", "विमानन कानून", "वायुयान", "विमान नियम",
        "విమానయాన చట్టం", "వాయుయాన", "విమాన నియమాలు",
    ), "Bharatiya Vayuyan Adhiniyam aircraft aviation aerodrome air transport registration safety"),
    ("tribunals", ("tribunals reforms",), (
        "tribunal appointments", "tribunal members", "न्याधिकरण सुधार", "ट्रिब्यूनल नियुक्ति",
        "ట్రిబ్యునల్ సంస్కరణలు", "ట్రిబ్యునల్ నియామకాలు",
    ), "Tribunals Reforms Act tribunal appointments members tenure service conditions"),
    ("rural_employment", ("viksit bharat",), (
        "rural employment guarantee", "rural wage work", "ग्रामीण रोजगार", "ग्रामीण रोजगार गारंटी", "ग्राम रोजगार",
        "గ్రామీణ ఉపాధి", "గ్రామీణ ఉపాధి హామీ", "గ్రామీణ కూలి పని",
    ), "Viksit Bharat G RAM G Act rural employment guarantee wage employment rural households work"),
    ("capf", ("central armed police forces",), (
        "central armed police", "capf administration", "केंद्रीय सशस्त्र पुलिस बल", "सीएपीएफ",
        "కేంద్ర సాయుధ పోలీసు దళాలు", "సీఏపీఎఫ్",
    ), "Central Armed Police Forces General Administration Act service administration appointment discipline"),
    ("election_commission", ("chief election commissioner",), (
        "election commissioner appointment", "chief election commissioner", "मुख्य चुनाव आयुक्त", "चुनाव आयुक्त नियुक्ति",
        "ప్రధాన ఎన్నికల కమిషనర్", "ఎన్నికల కమిషనర్ నియామకం",
    ), "Chief Election Commissioner Other Election Commissioners appointment conditions of service term of office"),
    ("direct_tax", ("direct tax vivad",), (
        "direct tax dispute settlement", "tax dispute settlement", "कर विवाद निपटान", "प्रत्यक्ष कर विवाद",
        "ప్రత్యక్ష పన్ను వివాద పరిష్కారం", "పన్ను వివాద పరిష్కారం",
    ), "Direct Tax Vivad se Vishwas Act tax arrears dispute settlement declaration payment"),
    ("farm_repeal", ("farm laws repeal",), (
        "repeal farm laws", "farm law repeal", "कृषि कानून वापसी", "कृषि कानून निरसन",
        "వ్యవసాయ చట్టాల రద్దు", "ఫామ్ లాస్ రిపీల్",
    ), "Farm Laws Repeal Act repeal farmers produce trade agreement essential commodities"),
    ("kerala_name", ("kerala alteration of name",), (
        "rename kerala", "kerala name change", "केरल का नाम बदलना", "केरल नाम परिवर्तन",
        "కేరళ పేరు మార్పు", "కేరళ పేరు మార్చడం",
    ), "Kerala Alteration of Name Act state name change Kerala alteration name"),
    ("police_identification", ("criminal procedure identification",), (
        "criminal identification measurements", "fingerprints police", "पुलिस पहचान माप", "अपराधी पहचान",
        "నేరస్థుల గుర్తింపు కొలతలు", "వేలిముద్రల సేకరణ",
    ), "Criminal Procedure Identification Act measurements fingerprints photographs police records"),
    ("civil_rights", ("protection of civil rights",), (
        "untouchability offence", "civil rights protection", "नागरिक अधिकार संरक्षण", "अस्पृश्यता अपराध",
        "పౌర హక్కుల రక్షణ", "అంటరానితనం నేరం",
    ), "Protection of Civil Rights Act untouchability enforcement civil rights offence"),
    ("sc_st", ("scheduled castes", "scheduled tribes"), (
        "caste atrocity", "scheduled caste protection", "जाति अत्याचार", "अनुसूचित जाति अत्याचार", "एससी एसटी अत्याचार",
        "కుల దాడి", "ఎస్సీ ఎస్టీ అట్రాసిటీ", "షెడ్యూల్డ్ కులాల రక్షణ",
    ), "Scheduled Castes Scheduled Tribes Prevention of Atrocities Act offence special court relief"),
    ("bns", ("bharatiya nyaya",), (
        "criminal offence punishment", "theft offence", "cheating offence", "भारतीय न्याय संहिता", "चोरी", "धोखाधड़ी अपराध",
        "భారతీయ న్యాయ సంహిత", "దొంగతనం", "మోసం నేరం",
    ), "Bharatiya Nyaya Sanhita offence punishment theft cheating assault criminal liability"),
    ("bnss", ("bharatiya nagarik suraksha",), (
        "fir police procedure", "file fir", "first information report", "एफआईआर", "प्राथमिकी", "पुलिस में रिपोर्ट",
        "ఎఫ్ఐఆర్", "మొదటి సమాచార నివేదిక", "పోలీసులకు ఫిర్యాదు",
    ), "Bharatiya Nagarik Suraksha Sanhita police procedure FIR cognizable offence investigation"),
    ("inter_services", ("inter services organisations",), (
        "joint services command", "inter services discipline", "संयुक्त सैन्य कमान", "अंतर सेवा संगठन",
        "త్రివిధ దళాల కమాండ్", "ఇంటర్ సర్వీసెస్ సంస్థలు",
    ), "Inter Services Organisations command control discipline service personnel"),
    ("cec", ("chief election commissioner",), (
        "election commissioners appointment", "चुनाव आयुक्त", "निर्वाचन आयुक्त", "ఎన్నికల కమిషనర్లు",
    ), "Chief Election Commissioner Election Commissioners appointment conditions service term"),
)


def expand_legal_query(query: str, indexed_act_names: Iterable[str] = ()) -> tuple[str, str, tuple[str, ...]]:
    """Return local English search terms, the best topic hint, and explicit Acts."""
    normalized = normalize_query_text(query)
    padded_query = f" {normalized} "
    expansions: list[str] = []
    matches: list[tuple[int, str, str]] = []
    matched_acts: list[str] = []

    for hint, act_fragments, aliases, expansion in _TOPICS:
        matched_lengths = [
            len(alias_norm)
            for alias in aliases
            if (alias_norm := normalize_query_text(alias))
            and f" {alias_norm} " in padded_query
        ]
        if matched_lengths:
            expansions.append(expansion)
            matches.append((max(matched_lengths), hint, expansion))
            for act in act_fragments:
                if act not in matched_acts:
                    matched_acts.append(act)

    # Full English Act names are a reliable hint even for Acts whose ordinary
    # subject wording does not need a dedicated multilingual topic row.
    for act_name in indexed_act_names:
        title = normalize_query_text(act_name)
        if title.startswith("the "):
            title = title[4:]
        if len(title) >= 10 and f" {title} " in padded_query:
            if act_name not in matched_acts:
                matched_acts.append(act_name)
            expansions.append(f"{act_name} provisions sections legal rules")

    hint = max(matches, default=(0, "", ""), key=lambda item: item[0])[1]
    unique_terms = list(dict.fromkeys(" ".join(expansions).split()))
    return " ".join(unique_terms), hint, tuple(matched_acts)


def act_match_boost(act_name: str, hint: str, explicit_acts: Iterable[str] = ()) -> float:
    """Return a modest rank tie-break for a linguistically matched Act."""
    name = normalize_query_text(act_name)
    if any(normalize_query_text(value).removeprefix("the ") in name for value in explicit_acts):
        return 0.30
    fragments = {
        row[0]: row[1] for row in _TOPICS
    }.get(hint, ())
    return 0.18 if any(normalize_query_text(fragment) in name for fragment in fragments) else 0.0
