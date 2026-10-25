# English Exam Maker

JSON을 입력받아 A4 2단 영어 시험지 PDF를 만드는 데스크톱/CLI 도구입니다. AI 호출 없이 실행되며, 어떤 AI로 전사하더라도 같은 문항 구조를 사용합니다.

```bash
pip install -r requirements.txt
python -m exam_maker validate examples/sample_exam.json
python -m exam_maker render examples/sample_exam.json -o output/sample.pdf
python -m exam_maker gui
```

PDF 전사는 [AI_CONVERSION_PROMPT.md](AI_CONVERSION_PROMPT.md), 입력 명세는 [exam_schema.json](exam_schema.json)을 참고하세요.

## 문항 형식

- **번호가 붙은 밑줄:** `answer_format: "inline"`, `options: []`. 번호는 `①[[u]]word[[/u]]`처럼 본문에 보존합니다. 기본 `auto`도 stem에 서로 다른 번호가 붙은 밑줄 두 개 이상이 있으면 별도 선지를 숨깁니다. 원본 options는 삭제하지 않고 검증 경고로 알립니다. 단일 밑줄 어휘 문제는 선지를 유지합니다. 별도 선지가 필요한 예외는 `answer_format: "options"`로 지정하세요. 공통 독해 passage의 밑줄을 고르는 하위 문항은 `inline`을 명시합니다.
- **문단 배열:** stem에는 지시문, context에는 먼저 주어진 문단(선택 사항), segments에는 `{"label": "(A)", "text": "..."}` 객체를 넣습니다. context는 박스, 각 segment는 라벨 뒤로 줄을 맞춘 독립 문단으로 출력합니다. 원본의 `(A)`, `[A]`, `Ⓐ` 라벨을 보존하세요. 기존 stem도 순서 지시문과 A부터 연속된 라벨을 인식하면 자동 분리합니다. 모호한 경우에는 명시적으로 segments를 작성하세요.
- **배점:** `points: 2` → `[2점]`. 배점이 없으면 생략합니다. 기존 stem 끝의 `2점`, `(2점)`, `[2점]`도 호환합니다. points와 기존 배점이 다르면 points를 사용하고 경고합니다.
- **선지:** 번호 없이 options에 넣습니다. 기본 `auto`는 짧은 선지 4~5개를 실제 글꼴 너비까지 확인해 2열로 배치합니다. 긴 선지는 1열이며, `options_columns: 1` 또는 `2`로 고정할 수 있습니다.
- **검증:** Validate/CLI에서 본문·박스·문단·선지의 인라인 태그를 검사하고, conversion_notes를 경고로 표시합니다. GUI에서 저장해도 원본 전사 데이터를 자동 변형하지 않습니다.

## 폰트

Windows의 Times New Roman/맑은 고딕을 우선 사용합니다. Linux에서는 Liberation Serif와 TrueType 한글 폰트(예: `fonts-nanum`), 원문자용 `fonts-noto-core`를 설치하세요. ReportLab이 지원하지 않는 PostScript 기반 CJK TTC는 건너뜁니다. 한글 폰트를 찾지 못하면 경고하며, 출력에서 한글 누락 여부를 확인해야 합니다.

사용자 폰트 폴더는 `EXAM_FONT_DIR`로 지정할 수 있습니다. Times New Roman은 `times.ttf`, `timesbd.ttf`, `timesi.ttf`, `timesbi.ttf`, 나눔고딕은 `NanumGothic.ttf`, `NanumGothicBold.ttf` 이름을 사용합니다. 글꼴 파일은 저장소에 포함하지 않습니다.

```bash
python -m unittest discover -s tests -v
```
