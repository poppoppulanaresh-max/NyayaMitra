import pytest

from legal_query import expand_legal_query

INDEXED_ACT_NAMES = (
    "The Indian Contract Act, 1872",
    "The Code of Civil Procedure, 1908",
    "The Limitation Act, 1963",
    "The Right to Information Act, 2005",
    "The Information Technology Act, 2000",
    "The Bharatiya Sakshya Adhiniyam, 2023",
    "The Negotiable Instruments Act, 1881",
    "The Legal Services Authorities Act, 1987",
    "The Motor Vehicles Act, 1988",
    "The Protection of Children from Sexual Offences Act, 2012",
    "The Rights of Persons with Disabilities Act, 2016",
    "The Maintenance and Welfare of Parents and Senior Citizens Act, 2007",
    "The Sexual Harassment of Women at Workplace Act, 2013",
)
EXPECTED_ACT = {
    "contract": "indian contract",
    "cpc": "code of civil procedure",
    "limitation": "limitation act",
    "rti": "right to information",
    "digital_evidence": "bharatiya sakshya",
    "negotiable_instruments": "negotiable instruments act",
    "legal_services": "legal services authorities",
    "motor_vehicles": "motor vehicles act",
    "pocso": "protection of children from sexual",
    "disability": "rights of persons with disabilities",
    "senior_citizens": "maintenance and welfare of parents",
    "workplace_harassment": "sexual harassment of women at workplace",
}


@pytest.mark.parametrize(
    ("question", "expected_hint"),
    [
        ("Under the Indian Contract Act, 1872, what makes an agreement a valid contract?", "contract"),
        ("Under the Code of Civil Procedure, 1908, what are the general steps in a civil suit?", "cpc"),
        ("How does the Limitation Act, 1963 address time limits for filing a suit?", "limitation"),
        ("Under the Right to Information Act, 2005, how can a person request information and what does the Act say about appeals?", "rti"),
        ("What do the Information Technology Act, 2000 and Bharatiya Sakshya Adhiniyam, 2023 say about electronic records and evidence?", "digital_evidence"),
        ("Under the Negotiable Instruments Act, 1881, what does the Act say about a cheque that is returned unpaid?", "negotiable_instruments"),
        ("Who may qualify for legal aid under the Legal Services Authorities Act, 1987?", "legal_services"),
        ("What does the Motor Vehicles Act, 1988 say about compensation after a road accident?", "motor_vehicles"),
        ("What does the Protection of Children from Sexual Offences Act, 2012 say about reporting an offence?", "pocso"),
        ("What rights or protections does the Rights of Persons with Disabilities Act, 2016 describe?", "disability"),
        ("I paid a contractor in advance, but they stopped work and will not return the money. What does the Indian Contract Act, 1872 say?", "contract"),
        ("My bank returned a cheque I received, and the person who gave it has not paid me. What does the Negotiable Instruments Act, 1881 say?", "negotiable_instruments"),
        ("An older parent says their adult child has stopped supporting them. What does the Maintenance and Welfare of Parents and Senior Citizens Act, 2007 provide?", "senior_citizens"),
        ("An employee says they faced unwelcome conduct at work. What process does the Sexual Harassment of Women at Workplace Act, 2013 describe?", "workplace_harassment"),
        ("भारतीय संविदा अधिनियम, 1872 के अनुसार किसी समझौते को वैध अनुबंध बनाने के लिए क्या आवश्यक है?", "contract"),
        ("सिविल प्रक्रिया संहिता, 1908 के अनुसार दीवानी मुकदमे के सामान्य चरण क्या हैं?", "cpc"),
        ("मुकदमा दायर करने की समय-सीमा के बारे में परिसीमा अधिनियम, 1963 क्या कहता है?", "limitation"),
        ("सूचना का अधिकार अधिनियम, 2005 के तहत जानकारी कैसे माँगी जा सकती है और अपील के बारे में अधिनियम क्या कहता है?", "rti"),
        ("सूचना प्रौद्योगिकी अधिनियम, 2000 और भारतीय साक्ष्य अधिनियम, 2023 इलेक्ट्रॉनिक रिकॉर्ड और साक्ष्य के बारे में क्या कहते हैं?", "digital_evidence"),
        ("परक्राम्य लिखत अधिनियम, 1881 के अनुसार, भुगतान के बिना लौटाए गए चेक के बारे में क्या प्रावधान है?", "negotiable_instruments"),
        ("विधिक सेवा प्राधिकरण अधिनियम, 1987 के तहत कौन कानूनी सहायता पाने के योग्य हो सकता है?", "legal_services"),
        ("सड़क दुर्घटना के बाद मुआवज़े के बारे में मोटर वाहन अधिनियम, 1988 क्या कहता है?", "motor_vehicles"),
        ("बाल लैंगिक अपराधों से संरक्षण अधिनियम, 2012 के अनुसार अपराध की सूचना देने के बारे में क्या प्रावधान है?", "pocso"),
        ("दिव्यांगजन अधिकार अधिनियम, 2016 में कौन-से अधिकार या संरक्षण बताए गए हैं?", "disability"),
        ("मैंने ठेकेदार को पहले से पैसे दिए, लेकिन उसने काम रोक दिया और पैसे लौटाने से मना कर रहा है। भारतीय संविदा अधिनियम, 1872 में क्या प्रासंगिक है?", "contract"),
        ("मुझे मिला चेक बैंक ने भुगतान किए बिना लौटा दिया है। परक्राम्य लिखत अधिनियम, 1881 क्या कहता है?", "negotiable_instruments"),
        ("एक वृद्ध माता-पिता कहते हैं कि उनका वयस्क बच्चा अब उनका भरण-पोषण नहीं कर रहा। माता-पिता और वरिष्ठ नागरिकों का भरण-पोषण तथा कल्याण अधिनियम, 2007 में क्या प्रावधान है?", "senior_citizens"),
        ("एक कर्मचारी का कहना है कि कार्यस्थल पर उसके साथ अनुचित व्यवहार हुआ। कार्यस्थल पर महिलाओं का यौन उत्पीड़न अधिनियम, 2013 में कौन-सी प्रक्रिया है?", "workplace_harassment"),
        ("భారతీయ ఒప్పందాల చట్టం, 1872 ప్రకారం ఒక ఒప్పందం చెల్లుబాటు కావడానికి ఏమి అవసరం?", "contract"),
        ("సివిల్ ప్రొసీజర్ కోడ్, 1908 ప్రకారం సివిల్ కేసులో సాధారణంగా ఉండే దశలు ఏమిటి?", "cpc"),
        ("కేసు దాఖలు చేయడానికి ఉండే కాల పరిమితి గురించి కాలపరిమితి చట్టం, 1963 ఏమి చెబుతుంది?", "limitation"),
        ("సమాచార హక్కు చట్టం, 2005 కింద సమాచారం ఎలా కోరవచ్చు? అప్పీల్ గురించి ఆ చట్టం ఏమి చెబుతుంది?", "rti"),
        ("సమాచార సాంకేతిక చట్టం, 2000 మరియు భారతీయ సాక్ష్య అధినియం, 2023 ఎలక్ట్రానిక్ రికార్డులు, సాక్ష్యాల గురించి ఏమి చెబుతున్నాయి?", "digital_evidence"),
        ("చెల్లింపుకాకుండా తిరిగి వచ్చిన చెక్కు గురించి నెగోషియబుల్ ఇన్‌స్ట్రుమెంట్స్ చట్టం, 1881 ఏమి చెబుతుంది?", "negotiable_instruments"),
        ("లీగల్ సర్వీసెస్ అథారిటీస్ చట్టం, 1987 ప్రకారం ఎవరు న్యాయ సహాయం పొందడానికి అర్హులు కావచ్చు?", "legal_services"),
        ("రోడ్డు ప్రమాదం తర్వాత పరిహారం గురించి మోటార్ వాహనాల చట్టం, 1988 ఏమి చెబుతుంది?", "motor_vehicles"),
        ("నేరాన్ని నివేదించడం గురించి పోక్సో చట్టం, 2012 ఏమి చెబుతుంది?", "pocso"),
        ("వికలాంగుల హక్కుల చట్టం, 2016లో ఏ హక్కులు లేదా రక్షణలు వివరించబడ్డాయి?", "disability"),
        ("కార్యాలయంలో తనకు అనుచిత ప్రవర్తన ఎదురైందని ఒక ఉద్యోగి చెబుతున్నారు. పని ప్రదేశంలో మహిళలపై లైంగిక వేధింపుల చట్టం, 2013 ఏ ప్రక్రియను వివరిస్తుంది?", "workplace_harassment"),
    ],
)
def test_sample_questions_route_to_the_expected_act(question, expected_hint):
    _, actual_hint, explicit_acts = expand_legal_query(question, INDEXED_ACT_NAMES)
    assert actual_hint == expected_hint or any(
        EXPECTED_ACT[expected_hint] in act.casefold() for act in explicit_acts
    )


def test_telugu_word_boundaries_preserve_combining_vowel_marks():
    _, hint, acts = expand_legal_query(
        "సివిల్ ప్రొసీజర్ కోడ్, 1908 ప్రకారం సివిల్ కేసులో సాధారణంగా ఉండే దశలు ఏమిటి?"
    , INDEXED_ACT_NAMES)
    assert hint == "cpc"
    assert "indian succession" not in acts

