// 訴願法第 77 條「有左列各款情形之一者，應為不受理之決定」的八款。
// 標題文字取自 docs/design/Gate.dc.html（本專案既有的設計參考稿，已對照條文
// 逐款覆核），不是本檔案自行改寫條文。目前只有第 2 款（逾法定期間）有真的
// 後端規則（procedural_review_service 的期間試算）；其餘七款都是實質法律
// 判斷或需要本系統沒有的案件庫／代理人資料，一律標示待人工確認，不假裝
// 系統查過或判定過。

export interface Article77Clause {
  no: number
  title: string
  hasRule: boolean
  manualCheckHint: string
}

export const ARTICLE_77_CLAUSES: Article77Clause[] = [
  {
    no: 1,
    title: '訴願書不合法定程式不能補正，或經通知補正逾期不補正',
    hasRule: false,
    manualCheckHint: '需人工核對訴願書是否具備法定記載事項，以及是否曾通知補正、補正期限是否已過。',
  },
  {
    no: 2,
    title: '提起訴願逾法定期間，或未於第 57 條但書所定期間內補送訴願書',
    hasRule: true,
    manualCheckHint: '日期規則只試算第 14 條期間；第 57 條但書的補送分支仍需補齊提出方式與補送日期。',
  },
  {
    no: 3,
    title: '訴願人不符第 18 條規定（當事人不適格）',
    hasRule: false,
    manualCheckHint: '需人工核對訴願人是否為原處分之相對人或利害關係人，涉及實質法律判斷，系統不判。',
  },
  {
    no: 4,
    title: '無訴願能力人未由法定代理人代為訴願行為',
    hasRule: false,
    manualCheckHint: '需人工核對訴願人是否為無訴願能力之自然人，以及有無法定代理人代為訴願。',
  },
  {
    no: 5,
    title: '法人或非法人團體未由代表人為訴願行為',
    hasRule: false,
    manualCheckHint: '需人工核對訴願人是否為法人或非法人團體，以及是否由合法代表人具名提起。',
  },
  {
    no: 6,
    title: '行政處分已不存在',
    hasRule: false,
    manualCheckHint: '需人工核對原處分是否仍然有效存在，有無經原處分機關撤銷或因故失效。',
  },
  {
    no: 7,
    title: '對已決定或已撤回之訴願事件重行提起',
    hasRule: false,
    manualCheckHint:
      '需人工查對本案是否已有前次訴願決定或撤回紀錄；本系統未串接案件庫，無法自動查核。',
  },
  {
    no: 8,
    title: '對非行政處分或不屬訴願救濟範圍之事項提起',
    hasRule: false,
    manualCheckHint: '需人工核對本案爭執事項是否構成行政處分、是否屬訴願救濟範圍，涉及實質法律判斷。',
  },
]
