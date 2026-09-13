// 訴願法第 77 條「有左列各款情形之一者，應為不受理之決定」的八款。
// 這裡只保留款次與標題。規則、輸入欄位及案件判定由程序審查 API 提供。

export interface Article77Clause {
  no: number
  title: string
}

export const ARTICLE_77_CLAUSES: Article77Clause[] = [
  {
    no: 1,
    title: '訴願書不合法定程式不能補正，或經通知補正逾期不補正',
  },
  {
    no: 2,
    title: '提起訴願逾法定期間，或未於第 57 條但書所定期間內補送訴願書',
  },
  {
    no: 3,
    title: '訴願人不符第 18 條規定（當事人不適格）',
  },
  {
    no: 4,
    title: '無訴願能力人未由法定代理人代為訴願行為',
  },
  {
    no: 5,
    title: '法人或非法人團體未由代表人為訴願行為',
  },
  {
    no: 6,
    title: '行政處分已不存在',
  },
  {
    no: 7,
    title: '對已決定或已撤回之訴願事件重行提起',
  },
  {
    no: 8,
    title: '對非行政處分或不屬訴願救濟範圍之事項提起',
  },
]
