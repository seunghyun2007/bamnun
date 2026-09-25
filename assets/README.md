Put `wake_up_ko.wav` here for the stage-3 voice prompt.

Generate one on the Pi with espeak-ng, or record your own (a familiar voice
is measurably more arousing than a synthetic one, which is itself a testable
claim worth a line in the report):

    sudo apt install -y espeak-ng
    espeak-ng -v ko "졸음운전 위험합니다. 지금 휴게소에 들르세요." -w assets/wake_up_ko.wav

Keep it under two seconds. A long prompt is a distraction in its own right.
