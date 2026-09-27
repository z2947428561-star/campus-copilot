"""把 XMUM 公开教务文档快照写入 data/raw_docs/*.md。

⚠️ 名称与实际行为的说明(重要,别误读):
    本脚本**不含任何网络采集代码** —— 全文件唯一的 import 是 `pathlib`,
    16 份文档的正文全部硬编码在下面的 `DOCS` 常量里,`main()` 只做写文件。
    它是"离线快照写入器",不是爬虫。
    原名 `collect_docs.py` 会让人以为它真的去采集,故更名为 `archive_docs.py`。

来源与合规(为什么保留硬编码):
- 正文来自 www.xmu.edu.my 公开发布的学生手册 PDF / 招生页面，
  以及 zs.xmu.edu.cn 的中国招生简章页面;每份文档头部标注来源 URL。
- 官网手册 PDF 是**图片版、无文本层**(pypdf 抽不出字),这是课件第10章
  §2.2.4(p12-16)列出的"扫描版 PDF"挑战。课件给的解法是 MinerU 在线解析
  (§2.2.4 p13-16,需要 MINERU_API_TOKEN);本项目暂未接入,
  因此正文以人工整理的形式固化为快照,保证离线可复现、不依赖网络。
- 原文为英文时保留英文(检索引用必须命中原文),关键处附中文要点,
  兼顾中文提问的跨语言召回。

跑法(项目根目录):
    .venv\\python scripts\\archive_docs.py     # 重跑覆盖,可重复执行
之后建库:
    .venv\\python scripts\\build_kb.py
"""
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_docs"

# (文件名, front matter 元数据, 正文)
DOCS = [
    # ---------------------------------------------------------- 考试与考勤
    (
        "attendance.md",
        """title: 考勤要求与禁考规定
source: https://www.xmu.edu.my/sites/default/files/2025-12/Undergraduate-Student-Handbook-2025.pdf
doc_type: attendance
lang: en
""",
        """# Attendance Requirements(本科生手册 2025 第 4.1 节)

The minimum attendance requirement for each course is 80%. Students who fail to meet this requirement without valid reasons accepted by the university or without obtaining prior permission from the Academic Affairs Office will be barred from taking the final examination for that course.

The student will receive an email notification one week before the examination week if they are barred from taking the final examination.

Students who have been barred from sitting for a final examination in any course will receive a Grade F. They may need to retake the course.

Students are required to ensure attendance in all assessment components, and any absences must be reported immediately to the respective lecturer for consideration. Remedial actions will be within the jurisdiction of the respective lecturer for the missed component.

Students are reminded to be punctual for lessons and all other learning activities. Late admission and attendance are at the discretion of the lecturer. It is the responsibility of students to ensure that their attendance is properly recorded.

## 中文要点
- 每门课最低出勤率要求 80%,不达标且无正当理由 → 禁止参加期末考试(barred)
- 被禁考的学生的该课程成绩记为 F,可能需要重修该课程
- 被禁考通知会在考试周前一周以邮件发出
- 缺勤任何考核环节须立即报告任课老师处理
""",
    ),
    (
        "exam_eligibility.md",
        """title: 期末考试资格
source: https://www.xmu.edu.my/sites/default/files/2025-12/Undergraduate-Student-Handbook-2025.pdf
doc_type: exam
lang: en
""",
        """# Eligibility for Final Examination(本科生手册 2025 第 4.2 节)

All registered and active students are required to participate in the final examinations for all courses as determined by the University, provided that they have completed the official course registration, cleared all outstanding fees with the University, and are not barred from the examination.

Students who have not paid the tuition fee will be prohibited from taking the final examination for the semester.

# Examination Attendance(第 4.4 节)

Students who fail to attend any final examination without written approval may receive a "Fail" grade for the particular course.

## 中文要点
- 参加期末考试的条件:完成正式选课、缴清所有费用、未被禁考
- 未缴学费者禁止参加当学期期末考试
- 无书面批准缺席期末考试 → 该课程成绩记为 Fail
""",
    ),
    (
        "exam_deferment.md",
        """title: 期末考试缓考规定
source: https://www.xmu.edu.my/sites/default/files/2025-12/Undergraduate-Student-Handbook-2025.pdf
doc_type: exam
lang: en
""",
        """# Deferment of Final Examination(本科生手册 2025 第 4.3 节)

Students may be allowed to defer their final examinations on medical and compassionate grounds and/or valid reasons accepted by the University. Common illness or fever will not be considered.

Students must complete a Deferment Form and attach a medical certificate or other relevant supporting documents to clarify that they are unable to take the examinations.

The completed form along with relevant supporting documents (E.g. original medical certificate issued by a clinical hospital, doctor's letter) must be submitted to Academic Affairs Office before the scheduled date of the examination for the said course, preferably before the examination week.

Late submissions with valid reasons may be considered for approval.

The Academic Affairs Office will review and endorse the deferment applications on a case-by-case basis.

Once the application is approved, the Academic Affairs Office will then defer the affected course(s) to week 1 of the following semester. If the application is not approved, the student will be required to sit for the final examination. He / She will receive a zero mark if he / she is absent from the examination of the said course.

## 中文要点
- 缓考(deferment)适用:医疗或体恤理由,普通感冒发烧不算
- 须填 Deferment Form 并附医院原始病假证明/医生信,在考试日期前交教务处
- 教务处逐案审批;批准后该课程考试推迟到下学期第 1 周进行
- 不批准仍缺考 → 该课程 0 分(这之后就需要重修)
- 这就是「补考」在 XMUM 的实际形态:因正当理由缓考到下学期第 1 周,
  而不是无限期补考;缺考/挂科没有额外免费补考机会,只能重修
""",
    ),
    (
        "exam_schedule_and_items.md",
        """title: 考试时间表与考场规则
source: https://www.xmu.edu.my/sites/default/files/2025-12/Undergraduate-Student-Handbook-2025.pdf
doc_type: exam
lang: en
""",
        """# Final Examination Schedule(本科生手册 2025 第 4.5 节)

The Academic Affairs Office will release each student's personal examination timetable one week before the final examination week, in accordance with the XMUM Undergraduate Academic Calendar.

Students are required to verify their list of courses and the details (examination date, time, and venue) of each course's examination before the examination week.

Students are advised to make any travel arrangements, such as flight schedules or rides, for the semester break after the examination week. The University will not entertain requests for changes due to clashes between examination dates and travel dates.

# Items Permitted in the Examination Room(第 4.6 节)

Permitted items: (i) Stationery (pens, pencils, rulers, and any other required equipment); (ii) Student ID for identification purposes; (iii) Water bottles without label or cover.

Students should place their belongings outside of the examination room. Invigilators are not responsible for the safekeeping of any personal belongings.

Students are NOT allowed to have unauthorized materials or equipment during the examination. If students are found with unauthorized materials (e.g. notes, textbooks, equipment with written texts, dictionaries, paper, pictures, electronic and smart devices), it will be assumed that they have used those materials and no defence will be accepted. All unauthorized materials will be confiscated.

Students must arrive at the designated examination room 15 minutes before the scheduled start time.

# Examination Conduct(SFS 手册 3.7.2)

You are not permitted to sit for a final examination if you turn up thirty (30) minutes or more after the commencement of a final examination. You are not allowed to leave an examination venue in the first one hour or the last 30 minutes of an examination.

You must bring along your Student ID and display it on your exam desk during the entire duration of a final examination.

## 中文要点
- 个人考试时间表在考试周前一周发布,须自行核对
- 因旅行安排与考试冲突提出的改期请求不予受理
- 考场可带:文具、学生证、无标签水杯;其他物品放考场外
- 迟到 30 分钟以上不得入场;开考首 1 小时与最后 30 分钟不得离场
- 携带未经授权材料(笔记/电子设备等)视为作弊,材料没收、不接受辩解
""",
    ),
    # ---------------------------------------------------------- 重修与成绩
    (
        "retake_rules.md",
        """title: 重修规定与费用
source: https://www.xmu.edu.my/sites/default/files/2025-12/SFS Student Handbook 2025 (Dec 2025 Semester).pdf
doc_type: academic
lang: en
""",
        """# Retaking a Course(SFS 学生手册 2025 第 2.5.9 节)

You may retake a course under one of the following circumstances:

(i) Failing a Course. If you receive a Grade F or a "void" grade in a course, you must retake the same course except in cases where there is no requirement to do so. You can retake a failed course multiple times as long as you have not exceeded the maximum allowable duration of your study.

(ii) Improving a Grade. If you attain a Grade D or better in a course but would like to improve your grade, you may retake the said course once. Only the higher marks and grade obtained in the two attempts will be used for the calculation of your CGPA at the end of your studies.

Retaking a course under any of the abovementioned circumstances involves the attendance of classes, and the submission of all coursework and the sitting for a final examination.

You will have to pay a fee based on the credit value of the course that you want to retake (per credit hour, RM 200 for courses without laboratory/computer-based practicals; RM 240 with practicals, foundation programmes).

Note on fees:
(i) You are not liable to pay the course retake fee if you fail a course and retake it the first time, and moreover, your failure in the course is not due to any misconduct or examination bar, or your failure does not come along with a non-fulfilment of the class attendance requirement.
(ii) You are liable to pay the course retake fee under the following circumstances even though it is your first retake attempt: a. If you intend to retake the same course to improve grades (allowed only once throughout your studies); or b. If you fail a course due to a nullification of your result arising from a penalty for misconduct or an examination bar stemming from a non-fulfilment of the class attendance requirement.
(iii) You are liable to pay the course retake fee for retaking a course from the second time onwards after failing the same course again.

# 与「补考」的区别(中文要点)

- 重修(retake)= 重新上课:完整重新出勤、交作业、参加期末考试,不是只补一场考试
- 挂科(Grade F 或 void)原则上必须重修同一门课,可在最长学习年限内多次重修
- 为提高成绩重修:只允许一次(针对 D 及以上成绩),CGPA 取两次中较高者
- 费用:首次因正常挂科重修免重修费;为提分重修/因舞弊或禁考挂科重修要缴费;
  第二次起重修一律缴费(每学分 RM200-240,预科标准)
- XMUM 没有独立「补考」制度:缺考走缓考(deferment,下学期第 1 周),
  挂科走重修(retake),两者路径不同
""",
    ),
    (
        "result_review.md",
        """title: 成绩复查规定
source: https://www.xmu.edu.my/sites/default/files/2025-12/SFS Student Handbook 2025 (Dec 2025 Semester).pdf
doc_type: academic
lang: en
""",
        """# Review of Final Course Assessment Results(SFS 学生手册 2025 第 2.5.8 节)

If you are not satisfied with your final result in a course, you may request for a review of assessment result. In a review of assessment result, your final examination answer script will be checked for the fairness of marks awarded and the possibility of errors in the summation of marks from each section of your script, and all your coursework will be checked as well to ensure all marks have been included in the calculation of your final result for the said course.

You must submit a completed "Request for a Review of Overall course assessment result" form together with a fee of RM50.00 on or before the stipulated deadline if you wish to have your result of a course reviewed. The paid fee will be refunded to you if errors are found in the marking of your final examination paper or the calculation of your final result for the said course. However, the paid fee will be forfeited if no errors are committed.

## 中文要点
- 对课程最终成绩不满意可申请复查:检查答卷判分公平性、分数加总错误、作业分遗漏
- 须在截止日前提交复查表 + RM50 费用
- 确有算分错误 → 退还费用;无错误 → 费用不退
""",
    ),
    (
        "prerequisites.md",
        """title: 先修课程规定
source: https://www.xmu.edu.my/sites/default/files/2025-12/SFS Student Handbook 2025 (Dec 2025 Semester).pdf
doc_type: academic
lang: en
""",
        """# Courses with Prerequisites(SFS 学生手册 2025 第 2.5.10 节)

You can enrol in most of the courses when they are offered in any semester during your entire period of study. However, there are some courses which you are not allowed to enrol in unless you have successfully completed and obtained at least a Grade D in the prerequisites.

Example: FCC3091 Academic Reading and Writing requires FCC1071 Introduction to Academic English.

## 中文要点
- 多数课程开课学期均可选修,但带先修要求的课程必须先修课至少拿 D 才能选
- 例:学术英语写作(FCC3091)需要先完成学术英语入门(FCC1071)
""",
    ),
    # ---------------------------------------------------------- 学籍变动
    (
        "withdrawal.md",
        """title: 退学与退费规定
source: https://www.xmu.edu.my/sites/default/files/2025-12/SFS Student Handbook 2025 (Dec 2025 Semester).pdf
doc_type: academic
lang: en
""",
        """# Withdrawal from a Registered Programme of Study(SFS 学生手册 2025 第 2.6 节)

You may withdraw from your registered programme of study by completing the "Programme Withdrawal Application form" at https://eservices.xmu.edu.my/. Your application for withdrawal will be processed within five working days.

You must settle any outstanding fees, room rental charges and utility bills, and return any loaned books to the library and any loaned items to the responsible departments or offices before you are allowed to leave the university.

Refund policy: Withdrawal submitted within the first two weeks of a new semester → 50% of tuition fee refunded. After the first two weeks → No refund.

If you withdraw within two weeks after commencement without having paid any tuition fee, you are liable to pay a penalty equivalent to 50% of the tuition fee. If you withdraw more than two weeks after commencement without having paid, the penalty is the full amount of tuition fee.

# Re-admission(第 2.7 节)

You may apply to be re-admitted to a programme subject to fulfilment of entry requirements. However, if you have been terminated from your studies due to disciplinary problems or poor academic performance, your application for re-admission will not be considered.

## 中文要点
- 退学走 e-services 系统申请,5 个工作日内处理
- 退学前须结清费用、退还图书馆借书
- 开学两周内退学退 50% 学费,之后不退
- 因纪律问题或学业差被开除者不可申请重新入学
""",
    ),
    (
        "leave_of_absence.md",
        """title: 请假与休学规定
source: https://www.xmu.edu.my/sites/default/files/2025-12/SFS Student Handbook 2025 (Dec 2025 Semester).pdf
doc_type: academic
lang: en
""",
        """# Leave of Absence(SFS 学生手册 2025 第 3.5 节)

Authorised leave of absence circumstances: (i) Sickness; (ii) Accident; (iii) Driving test; (iv) Attendance of a memorial service; (v) Essential dental treatments; (vi) Fulfilment of national service duties; (vii) Participation in competitions or events as a university representative; (viii) Participation in activities organised by the university; (ix) Attendance of religious ceremonies or activities; (x) Compassionate reasons; (xi) Others (any other valid and justifiable reasons).

Absence under authorised leave shall not be counted towards your absences. The length of authorised leave ranges from one (1) to fourteen (14) calendar days. If your intended absence is longer than fourteen calendar days, you shall be advised to take a study break instead.

Unauthorised leave: If you are absent without authorisation for a continuous period of fifteen (15) calendar days or more, you shall be deemed as having no interest in continuing your studies and thus be terminated from your programme of study.

All leave applications must be submitted via the official e-Service system (https://eservices.xmu.edu.my). Leave applications submitted via email or verbal requests will not be processed. The e-Leave Service system is only accessible within the campus network. For Sick Leave, students must submit the original physical medical certificate (MC) to the School Office at Room B1#217 after completing the online application.

# Attendance Below 60%(第 3.4 节)

You may receive a grade of no higher than Grade D for a course, with no right to appeal, if your attendance rate dips below 60% in any of the teaching and learning activities for the course, and you shall not be accorded an opportunity for resitting the final examination or undertaking a supplementary assessment. If you obtain a Grade F in a course in which your attendance rate is below 60%, you must retake the course and pay the course retake fee.

## 中文要点
- 合规请假事由:疾病、事故、驾照考试、丧礼、牙科治疗、兵役、代表学校参赛等
- 授权请假不计缺勤;一次最多 14 天,超过 14 天应申请 study break(休学)
- 未经批准连续缺勤 15 天以上 → 视为放弃学业,开除学籍
- 请假必须走 e-Service 系统,邮件/口头无效;病假还要交纸质 MC 到 B1#217
- 出勤率低于 60%:该课最高只能拿 D,且没有重考(resit)或补充考核(supplementary)机会
""",
    ),
    # ---------------------------------------------------------- 申诉
    (
        "appeals.md",
        """title: 成绩申诉与纪律申诉
source: https://www.xmu.edu.my/sites/default/files/2025-10/Xmum Student Book 2026 (2).pdf
doc_type: academic
lang: en
""",
        """# Appeal Rules and Regulations(大学学生手册 2026 第 5.2 节)

Appeals that challenge the academic judgment of examiners will not be permitted. Only the candidate themselves can submit an appeal on their behalf. Appeals are only applicable for courses that have a final examination. Appeals can only be made to review the final examination result — marks obtained in tests, quizzes, mid-term tests, assignments, or other course components will not be considered.

Students should be aware that submitting an appeal does not guarantee a change of marks. In some cases, the second examiner may even lower the marks if it is determined that the original marks were given incorrectly.

# Appeal Procedures for Reviewing the Final Examination Result(第 5.3 节)

To initiate an appeal, the student must complete the "Student Appeal Form", obtainable from the Exam Unit. The completed form should be submitted to the Finance Office for invoicing of the appeal fee — an appeal fee of RM50.00 per course. After payment, submit the form and letter with the payment receipt to the Exam Unit.

The outcome of the appeal will be communicated in writing within three weeks after the end of the appeal period. The decision reached through the appeal is final. An appeal is considered successful if the newly awarded mark is higher, in which case the fee will be refunded.

# Appeal against Academic Misconduct / Disciplinary Matters(第 5.4 节)

Appeals against disciplinary decisions must be submitted within 14 working days of receiving the letter of decision from the Student Discipline and Behaviour Committee (SDBC). The outcome will be communicated in writing within two weeks of filing.

## 中文要点
- 不能挑战阅卷老师的学术判断;只能本人申诉;只针对有期末考试的课程、只能复核期末成绩
- 申诉不保证加分,查出错还可能降分
- 流程:领表 → 财务处开 RM50/科账单 → 付款 → 连收据交考试组
- 三周内书面通知结果;成功(分数变高)退费;结果为最终决定
- 纪律申诉须在收到决定信后 14 个工作日内提出
""",
    ),
    # ---------------------------------------------------------- 毕业与费用
    (
        "graduation.md",
        """title: 毕业与学位要求
source: https://www.xmu.edu.my/sites/default/files/2025-10/Xmum Student Book 2026 (2).pdf
doc_type: academic
lang: en
""",
        """# Graduation Requirements(大学学生手册 2026 第 6.0 节)

In order to be conferred a degree, students must meet all of the following conditions:
i. Fulfilment of the minimum total credit hours required for graduation from their programme;
ii. Attainment of a minimum CGPA of 2.0;
iii. Having received at most one "Conditional Pass" status;
iv. Full settlement of all outstanding fees and charges.

Students may be permitted to extend the duration of their study at XMUM, subject to the rules and regulations of the university.

Academic Affairs Office: Room A3#702, Monday to Friday 8.30am–5.30pm (lunch 12.30–1.30pm), xmumac@xmu.edu.my.

## 中文要点
- 拿学位四个条件:修满学分、CGPA ≥ 2.0、「有条件通过」状态最多一次、结清费用
- 符合规定可申请延长学习年限
- 教务处 A3#702,工作日 8:30-17:30
""",
    ),
    (
        "fees.md",
        """title: 学费与行政费用
source: https://www.xmu.edu.my/sites/default/files/2025-10/Xmum Student Book 2026 (2).pdf
doc_type: finance
lang: en
""",
        """# Tuition Fees and Administrative Fees(大学学生手册 2026 第 7.1 节)

International students are required to pay: Security Deposit RM1,000 (refundable); International Student Fee RM2,500 per academic year.

# Fee Payment(第 7.2 节)

Students are required to pay the first semester fees upon enrolment and subsequently within seven (7) working days from the commencement of the new semester.

# 中国招生简章参考学费(2025 年入学,林吉特/学年)

计算机科学与技术、软件工程 29,000;人工智能、网络空间安全、数据科学与大数据技术、自动化 30,000;国际学生手续费 2,500/学年(涵盖签证、体检、保险)。住宿费双人间每人每月 340-390。

## 中文要点
- 国际生:押金 RM1,000(可退)+ 国际学生费 RM2,500/学年
- 新学期学费须在开学后 7 个工作日内缴清(否则禁考)
- 未缴学费会被禁止参加期末考试
""",
    ),
    # ---------------------------------------------------------- 奖学金与签证
    (
        "scholarship.md",
        """title: 奖学金与助学金
source: https://www.xmu.edu.my/admissions/scholarships-financial-aid
doc_type: scholarship
lang: en
""",
        """# Merit Scholarship(入学奖学金)

Based on number of Grade A (including A+, A, A-) in SPM/O-Level/UEC/STPM/A-Level. Examples for undergraduate programmes: 3A → 15%, 4A → 30%, 5A → 45%, 6A → 70%, 7A → 100%.

For pre-university qualifications (SACE/AUSMAT/IBD/MUFY): CGPA ≥ 3.00 → 25%, CGPA ≥ 3.50 → 50%, CGPA ≥ 3.75 → 75%; ATAR 90 → 25% up to ATAR 98 → 100%.

XMUM Progression Scholarship (foundation to undergraduate): CGPA ≥ 3.00 → 25%, CGPA ≥ 3.30 → 50%, CGPA ≥ 3.50 → 100%.

# Study Grant(资助)

Teacher's Children 10%; Sibling (兄弟姐妹在读) 15%; Bumiputera & Indian Community 20%. Applicants can only apply for either the scholarship or the study grant, whichever is higher.

# Scholarship Renewal Policy(续领政策)

Renewal depends on academic achievement at the end of each academic year compared with peers of the same programme and intake: scholarship 80-100% requires top 25%; 50-80% requires top 35%; 25-50% requires top 45%; ≤25% requires top 70%. Study grant renewal requires minimum CGPA of 2.00.

## 中文要点
- 入学奖学金按 A 数量或预科 CGPA 定比例,最高 100% 学费
- 在读续领按同专业同届排名:80-100% 奖学金需前 25%
- 奖学金与助学金只能二选一,取高者
""",
    ),
    (
        "visa_renewal.md",
        """title: 国际学生签证续签要求
source: https://zs.xmu.edu.cn/info/1042/33242.htm
doc_type: visa
lang: zh
""",
        """# 学生签证续签规定(2025 年中国招生简章)

根据马来西亚移民局的规定,原则上要求国际学生(包括中国学生)签证每年续签一次,以下两项为续签的基本条件,如未达到有可能因学业问题被遣送回国:

1. 前一学年 CGPA(平均累积学分绩点)不低于 2.0;
2. 各门课程的课堂出勤率均不低于 80%。

学生须配合学校完成马来西亚移民局规定的各项签证手续,在规定时间内提交护照等材料完成各类签证手续,完成学业后在马来西亚境内配合完成学生签证取消手续。

## 关键数字
- 签证续签学业门槛:CGPA ≥ 2.0
- 签证续签出勤门槛:每门课出勤率 ≥ 80%
""",
    ),
    (
        "handbook_index.md",
        """title: 学生手册索引(官方文件清单)
source: https://www.xmu.edu.my/campus-life/student-handbook
doc_type: general
lang: en
""",
        """# Student Handbook(官方手册清单,下载自 www.xmu.edu.my/campus-life/student-handbook)

- Student Handbook 2027 — Xmum Student Book 2027 FA.pdf (updated 2026-09-07)
- Foundation Student Handbook 2026 — SFS Student Handbook 2026 (August 2026 Semester).pdf (updated 2026-08-01)
- International Student Handbook (March 2025)
- MBA Student Handbook 2026 (updated 2026-02-23)
- Undergraduate Student Handbook 2026 — Xmum Student Book 2026 (2).pdf (updated 2025-10-22)
- Postgraduate Student Handbook 2026 (updated 2026-01-30)
- Dress Code Policy(着装规范)

## 中文要点
- 官方手册按学生类型分:本科/预科/国际生/MBA/研究生
- 本项目知识库正文取自 Undergraduate Student Handbook、SFS Handbook、
  University Student Book 及招生/奖学金公开页面
""",
    ),
    (
        "eservices.md",
        """title: 电子服务平台(e-Services)与常用办公室
source: https://www.xmu.edu.my/sites/default/files/2025-12/SFS Student Handbook 2025 (Dec 2025 Semester).pdf
doc_type: general
lang: en
""",
        """# e-Service System(SFS 学生手册 2025)

All leave applications must be submitted via the official e-Service system, accessible at https://eservices.xmu.edu.my. For password-related issues, students may reset their password at https://id.xmu.edu.my.

Important notes:
(i) Leave applications submitted via email or verbal requests will not be processed.
(ii) The e-Leave Service system is only accessible within the campus network.
(iii) For Sick Leave applications, students must submit the original physical medical certificate (MC) to the School Office at Room B1#217 after completing the online application.

Programme withdrawal application form is also at https://eservices.xmu.edu.my.

# 常用联系方式

Academic Affairs Office: Room A3#702, xmumac@xmu.edu.my, Mon–Fri 8.30am–5.30pm (lunch 12.30–1.30pm). International student recruitment: int.enquiry@xmu.edu.my.

## 中文要点
- 请假/退学申请统一走 e-services 系统(https://eservices.xmu.edu.my)
- 密码重置:https://id.xmu.edu.my
- e-Leave 系统只能校园网内访问;病假须线下交 MC 到 B1#217
- 教务处 A3#702 / xmumac@xmu.edu.my
""",
    ),
]


def main():
    """把 DOCS 里的 16 份快照写入 data/raw_docs/。

    注意:这里没有下载/解析步骤 —— 见模块 docstring 的说明。
    旧版此处会删除两个"抓取临时文件"(_download_ug2025.pdf / _ug2025_full.txt),
    但本脚本从没有代码生成过它们,属早期爬虫版本的残留,已删除
    (避免让人误以为存在采集能力)。
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    for filename, meta, body in DOCS:
        content = f"---\n{meta}---\n{body}"
        (DOCS_DIR / filename).write_text(content, encoding="utf-8")
        print(f"写入 {filename}")

    print(f"\n共 {len(DOCS)} 份文档 → {DOCS_DIR}")
    print("下一步:.venv\\python scripts\\build_kb.py  (建向量库)")


if __name__ == "__main__":
    main()
