# 기존 영어 문제 PDF → Exam Maker JSON 변환 프롬프트

아래 프롬프트와 함께 다음 세 파일을 AI에게 제공한다.

1. 변환 대상 PDF
2. `exam_schema.json`
3. `examples/sample_exam.json`

PDF가 크면 “1~20번”, “21~40번”처럼 번호 범위를 나눠 실행한다. 각 조각을 받은 뒤 문항 번호와 원문을 사람이 한 번 대조하고 마지막에 `blocks` 배열만 순서대로 합친다.

---

## 복사용 프롬프트

```text
첨부한 영어 문제 PDF를 English Exam Maker의 입력 JSON으로 전사해 줘.

중요: 이 작업의 목적은 문제를 풀거나 재작성하는 것이 아니라, PDF의 문제 내용을 지정된 JSON 구조로 정확히 옮기는 것이다. 첨부한 exam_schema.json을 반드시 따르고, examples/sample_exam.json의 구조와 인라인 표기법을 참고하라.

[전사 원칙]
1. 문제 문장, 지문, 선지, 문항 번호, 공통 지시문을 원문 그대로 보존한다. 문법·철자·표현을 임의로 교정하거나 의역하지 않는다.
2. 정답, 해설, 풀이, 난이도 평가는 출력하지 않는다. 원본에 정답·해설이 함께 있더라도 이번 결과에서는 제외한다.
3. 페이지 머리말, 쪽수, 출판사명, 워터마크, 강의 메모, 장식용 문구는 문제 내용이 아니면 제외한다.
4. 읽을 수 없는 부분을 추측하지 않는다. 해당 자리에 [[UNREADABLE: page N, location]]이라고 기록하고, 마지막의 conversion_notes 배열에도 남긴다.
5. 출력은 설명이나 Markdown 코드블록 없이, UTF-8 JSON 한 개만 반환한다.

[문항 표현]
1. 일반 문제, 빈칸 문제, 밑줄 문제는 모두 type: "question"을 사용한다.
2. 빈칸은 stem 안에서 [[blank:N]]으로 표시한다. N은 주변 글자 크기를 기준으로 한 대략적인 em 너비이며 보통 3~8을 사용한다. 원본 빈칸 길이를 보고 판단한다.
3. 밑줄 친 단어나 구절은 [[u]]원문[[/u]]로 표시한다.
4. 굵게와 기울임이 의미상 필요한 경우 각각 [[b]]...[[/b]], [[i]]...[[/i]]를 사용한다.
5. 선지는 options 배열에 번호 기호 없이 순서대로 넣는다. 프로그램이 ①, ②, ③, ④를 자동으로 붙인다.
6. 짧은 단어·짧은 구 선지 네 개는 options_columns: 2로 설정한다. 문장형 선지나 줄바꿈 가능성이 큰 선지는 options_columns: 1로 설정한다. 판단이 애매하면 "auto"를 사용한다.
7. 공통 문항 범위와 지시문은 type: "section"으로 만든다. 예: heading: "[1-4]", instruction: "Choose the one that best completes the sentence."

[독해 표현과 페이지 규칙]
1. 하나의 지문을 공유하는 모든 문항은 type: "reading" 한 블록에 묶는다.
2. reading 블록에는 passage와 questions를 넣고 start_at_column_top: true로 설정한다.
3. passage의 문단 구분은 빈 줄 하나, 즉 문자열 안의 \n\n으로 보존한다. 문장 중간에서 PDF의 시각적 줄바꿈만 발생한 것은 공백으로 합친다.
4. 지문에 밑줄·빈칸이 있으면 question과 같은 인라인 표기법을 사용한다.
5. 한 지문 묶음이 A4 한 페이지의 두 열에 담기 어려울 정도로 매우 길면 내용을 삭제하지 말고 reading 블록을 유지하며 conversion_notes에 "layout review required"를 기록한다. 임의로 지문을 둘로 쪼개지 않는다.

[번호와 누락 검증]
1. 지정된 변환 범위의 첫 번호와 마지막 번호를 확인한다.
2. 모든 번호가 한 번씩 존재하는지 확인하고, 중복·누락이 있으면 추측해 메우지 말고 conversion_notes에 기록한다.
3. 각 객관식 문항의 선지 개수와 순서를 원본과 대조한다.
4. 지문 공유 범위를 원본의 문항 범위 표기와 대조한다.
5. 최종 JSON을 반환하기 전에 모든 [[u]], [[b]], [[i]] 태그가 올바르게 닫혔는지 확인한다.

[출력 구조]
- document: 시험지 메타데이터와 시험 코드를 기록하되 개인 풀이용 출력이므로 show_header와 show_candidate_table은 반드시 false로 설정한다. series_title은 "D-SERIES 006", series_title_every_page는 true로 설정한다. 제목·부제·형 정보는 큰 시험 정보표로 표시되지 않는다.
- style: examples/sample_exam.json의 값을 그대로 사용한다. font_family은 반드시 "Times New Roman"이다.
- blocks: 원본 순서대로 section, question, reading, page_break 블록을 배열에 넣는다. 원본의 단순 페이지 경계는 page_break로 옮기지 않는다. 새로운 대단원 또는 반드시 새 페이지여야 하는 경계만 page_break를 사용한다.
- conversion_notes: 스키마 외 검수 메모 배열이다. 메모가 없으면 빈 배열로 둔다. 실제 프로그램에 넣기 전에는 사람이 검수한 뒤 이 필드를 삭제한다.

이번 작업 범위: [여기에 페이지 또는 문항 번호 범위를 입력]
```

---

## 후속 검수 프롬프트

AI가 JSON을 만든 뒤 PDF와 JSON을 다시 함께 주고 아래처럼 검수시킨다.

```text
첨부 PDF의 지정 범위와 exam JSON을 대조해라. 문항 번호, 지문 문장, 빈칸 위치, 밑줄 범위, 선지 개수와 순서만 검사하고 문제는 풀지 마라. 차이가 있으면 수정된 JSON 전체를 반환하지 말고, JSON Pointer 경로와 수정 전/후 값만 목록으로 반환해라. 확신할 수 없는 항목은 추측하지 말고 PDF 페이지와 위치를 표시해라.
```
