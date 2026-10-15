from captions.worker.segmenter import Segmenter


def texts(segs):
    return [(s.seq, s.text, s.final) for s in segs]


def test_interim_then_stable_sentence_becomes_final():
    s = Segmenter()
    assert texts(s.on_interim("The Lord is")) == [(1, "The Lord is", False)]
    out = s.on_stable("The Lord is my shepherd.")
    assert texts(out) == [(1, "The Lord is my shepherd.", True), (2, "", False)]


def test_partial_shows_committed_plus_interim_and_dedupes():
    s = Segmenter()
    s.on_stable("Please open your")
    assert texts(s.on_interim("Bibles")) == [(1, "Please open your Bibles", False)]
    assert s.on_interim("Bibles") == []


def test_multiple_sentences_in_one_stable_chunk():
    s = Segmenter()
    out = s.on_stable("Welcome. We're glad you're here. Please")
    finals = [t for t in texts(out) if t[2]]
    assert finals == [(1, "Welcome.", True), (2, "We're glad you're here.", True)]
    assert texts(out)[-1] == (3, "Please", False)


def test_endpoint_flushes_unpunctuated_text():
    s = Segmenter()
    s.on_stable("let us pray")
    out = s.on_endpoint()
    assert texts(out)[0] == (1, "let us pray", True)


def test_abbreviations_do_not_split():
    s = Segmenter()
    out = s.on_stable("Thank you Dr. Smith for coming")
    assert all(not seg.final for seg in out)


def test_long_run_on_is_split():
    s = Segmenter(max_chars=60)
    long = "and we walked and we talked, and the road went on and on, and still we kept going forward"
    out = s.on_stable(long)
    finals = [seg for seg in out if seg.final]
    assert finals and all(len(f.text) <= 60 for f in finals)


def test_flush_drops_unstable_interim():
    s = Segmenter()
    s.on_stable("Amen")
    s.on_interim("and")
    out = s.flush()
    assert (1, "Amen", True) in texts(out)
    assert all("and" not in seg.text for seg in out if seg.final)


def test_long_sentence_is_cut_at_a_clause_break_before_its_period():
    seg = Segmenter()
    out = seg.on_stable("In the beginning God created the heavens and the earth, and the earth was without form")
    finals = [s.text for s in out if s.final]
    assert finals == ["In the beginning God created the heavens and the earth,"]
    assert seg.committed == "and the earth was without form"


def test_short_text_with_a_comma_waits_for_more():
    seg = Segmenter()
    out = seg.on_stable("Good morning, church")
    assert not [s for s in out if s.final]
    assert seg.committed == "Good morning, church"


def test_early_comma_is_not_used_as_a_cut():
    seg = Segmenter()
    out = seg.on_stable("Well, we are going to look at the passage that we read together last week")
    assert not [s for s in out if s.final]
