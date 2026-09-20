import { Fact, FactProvider } from './Fact'

const INVENTORY = [
  ['ExposureUnit', 938, 'What is being insured, in seven flavours', 100],
  ['Coverage', 366, 'Limits, deductibles, sublimits', 39],
  ['Endorsement', 253, 'Real form numbers and edition dates', 27],
  ['Claim', 179, 'Loss history, paid and reserved', 19],
  ['Submission', 158, 'The queue itself', 17],
  ['Building', 129, 'TIV, construction type, year built', 14],
  ['Policy', 113, 'Premium and the bridge to exposure', 12],
  ['Location', 70, 'State, coordinates, hazard tags', 7.5],
  ['Insured', 30, 'The accounts everything hangs off', 3.2],
  ['Contact', 14, 'Broker-side producers', 1.5],
  ['Underwriter', 8, 'Who the work gets assigned to', 0.9],
  ['Broker', 6, 'Distribution, tiered', 0.6],
]

const DECLINES = [
  [4, 'insufficient_controls', 'no factor in the table covers this'],
  [3, 'loss_history', 'scored, weight 12'],
  [3, 'broker_withdrew', 'not an underwriting decision'],
  [2, 'outside_appetite', 'scored, hard stop'],
  [2, 'cat_exposure_aggregation', 'partly — via concentration'],
]

const LEDGER = [
  ['Open submissions have no policy attached', "Score the account's footprint, not the submission record"],
  ['Two equally short routes from Policy to Building', 'Keep every minimal route, merge into one expand'],
  ['Over half of locations sit outside the footprint', 'Hard stops cap the score at 25 instead of zeroing it'],
  ['61% of incurred loss is still in reserves', 'Score incurred, never paid'],
  ['Claims span lines an account never asked to renew', 'Scope loss to the line, disclose the remainder'],
  ['Unquoted submissions carry no premium', 'Use the expiring same-line term, labelled indicative'],
  ['Every location has usable coordinates', 'Weather enrichment on 21 of 21, no geocoding step'],
]

export default function Dataset() {
  return (
    <div className="panel doc">
      <FactProvider>
        <div className="notes-doc">
          <p className="hintbar">
            <span className="m">Hover</span>
            <span>
              Underlined figures carry the evidence behind them and what each one forced in the
              agent's design. Tap them on a touchscreen.
            </span>
          </p>

          <section>
            <p className="kicker">Inventory · all 12 resources</p>
            <h2>What actually arrives</h2>
            <p>
              The handler exposes twelve resources totalling{' '}
              <Fact
                inData="ExposureUnit 938 · Coverage 366 · Endorsement 253 · Claim 179 · Submission 158 · Building 129 · Policy 113 · Location 70 · Insured 30 · Contact 14 · Underwriter 8 · Broker 6. Every resource has contiguous unique ids from 1 to its total, so nothing was missed by pagination."
                forAgent="The whole dataset is about 900KB. That is small enough to bulk-fetch, so the agent pages each resource once with an $in filter instead of issuing a query per submission. Triaging the live queue costs 7 API calls, not 21."
              >
                2,264 records
              </Fact>
              . The challenge withholds a field-by-field reference on purpose, so the agent calls{' '}
              <code>action: "schema"</code> at startup and learns the shape of the world before it
              asks for anything specific.
            </p>

            <div style={{ overflowX: 'auto', margin: '20px 0 4px' }}>
              <table className="grid">
                <thead>
                  <tr>
                    <th>Resource</th>
                    <th style={{ textAlign: 'right' }}>Records</th>
                    <th>Role in the queue</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {INVENTORY.map(([name, n, role, pct]) => (
                    <tr key={name}>
                      <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{name}</td>
                      <td className="num" style={{ textAlign: 'right' }}>{n}</td>
                      <td style={{ color: 'var(--ink-2)' }}>{role}</td>
                      <td style={{ width: 130 }}>
                        <div className="sharebar">
                          <i style={{ width: `${pct}%` }} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p>
              <Fact
                inData="census_segment 283, vehicle 193, professional 185, driver 154, location 88, underlying_layer 21, digital_asset 14. Only 88 carry kind: location — but 749 of the 938 hold a location reference, including every census_segment, vehicle and professional unit."
                forAgent="Filtering exposure units to kind == 'location' would have reached 88 units and missed 661 more that still sit at a real address. The agent walks whatever the expand returns and recognises records structurally, rather than trusting the kind label."
              >
                ExposureUnit is the largest table
              </Fact>{' '}
              and the most varied: it models fleets, staff rosters, census tiers and cyber assets
              under one roof. For a property book only a slice matters, but the slice is not the one
              the <code>kind</code> field suggests.
            </p>
          </section>

          <section>
            <p className="kicker">Submission · Policy</p>
            <h2>The queue is smaller than it looks</h2>
            <p>
              There are{' '}
              <Fact
                inData="bound 113, declined 14, lost 10, cleared 7, received 7, quoted 7. Received dates run 15 Apr 2024 to 6 Jun 2026."
                forAgent="A tool that ranks all 158 rows is mostly ranking history. The agent defaults to the open statuses and offers the rest behind a toggle, so the first screen is work an underwriter can still act on."
              >
                158 submissions
              </Fact>
              , but 137 of them have already been decided. The genuinely open queue — received,
              cleared or quoted — is{' '}
              <Fact
                inData="7 received, 7 cleared, 7 quoted. Their lines: property 6, cgl 5, health 5, auto 3, cyber 1, lpl 1. Twenty-seven submissions across the full set have no underwriter assigned."
                forAgent="Twenty-one rows is small enough to deep-dive every one. That is why enrichment and LLM write-ups run across the whole live queue rather than a top-N slice — the cost argument for sampling disappears."
              >
                21 submissions
              </Fact>
              , and the appetite guidelines cover commercial property only, which leaves{' '}
              <Fact
                inData="Submissions 126, 133, 134, 138, 141 and 143. Requested limits run $1M to $25M. They belong to five accounts — insured 19 appears twice."
                forAgent="Six addressable rows is not a queue worth a ranking algorithm on its own. So the agent scores all 21 and gives the fifteen out-of-line submissions an explicit reason rather than filtering them away — an underwriter still needs to see why cgl and health were skipped."
              >
                six
              </Fact>{' '}
              truly in scope.
            </p>

            <div className="funnel">
              {[
                ['All submissions on file', 158, 100],
                ['Still open — received, cleared, quoted', 21, 13.3],
                ['Open and in the property book', 6, 3.8],
              ].map(([lbl, val, w]) => (
                <div className="rung" key={lbl}>
                  <div className="top">
                    <span className="lbl">{lbl}</span>
                    <span className="val">{val}</span>
                  </div>
                  <div className="track">
                    <i style={{ width: `${w}%` }} />
                  </div>
                </div>
              ))}
            </div>

            <div className="callout">
              <h3>The finding that set the architecture</h3>
              <p>
                <code>Policy.submission</code> covers exactly the{' '}
                <Fact
                  inData="113 policies reference 113 distinct submissions, one to one — every bound submission and no other. Policy ids run 1001–1113; submission ids run 1–158."
                  forAgent="That one-to-one mapping is a labelled set: 113 accounts the carrier actually wrote. It is the natural sanity check for whether the scorer's notion of 'in appetite' resembles what this book already did."
                >
                  113 bound submissions
                </Fact>{' '}
                and <strong>none of the 21 open ones</strong>. There is no policy hanging off a live
                submission, so premium, TIV, construction type, building year and loss history are
                all unreachable by that route — and those are precisely what the appetite table
                scores on.
              </p>
            </div>

            <p>
              The way through is the one an underwriter takes on new business: work the{' '}
              <strong>account</strong>, not the piece of paper. From <code>Submission.insured</code>{' '}
              the agent reaches the account's headquarters, the buildings on its prior policies, and
              its claim record.
            </p>

            <div className="chain">
              {'Submission → Insured → '}
              <b>hq</b>
              {' → Location → Building        TIV · construction · year built\nSubmission → Insured ← '}
              <b>Policy</b>
              {' → exposure_units → Location → Building\n                            → premium on the expiring same-line term\n                            → '}
              <b>claims</b>
              {' → Claim                 five-year loss history'}
            </div>

            <p style={{ marginTop: 20 }}>
              The agent never has that path written into it. It searches the discovered schema for
              the field holding the number it needs and asks for a route, which returns{' '}
              <Fact
                inData="paths_between('Policy', 'Building') returns both ['insured','hq','buildings'] and ['exposure_units','location','buildings']. Both are three hops, and they reach different buildings."
                forAgent="Taking whichever route a breadth-first search found first would silently drop half an account's footprint. The planner keeps every minimal route and merges them into a single expand stage, so one query walks both."
              >
                two equally short paths
              </Fact>{' '}
              to Building — not one.
            </p>
          </section>

          <section>
            <p className="kicker">Location · Building</p>
            <h2>The book sits largely outside its own appetite</h2>
            <p>
              The guidelines name eleven acceptable states, six of them targets. The dataset's
              seventy locations span twelve states, and{' '}
              <Fact
                inData="In footprint: CA 19, FL 7, CO 4, GA 2 — 32 of 70. Outside: TX 9, TN 8, IL 5, AZ 4, WA 4, NJ 4, MO 2, MA 2 — 38 of 70."
                forAgent="Primary risk state is a hard stop, and it would disqualify over half the addresses on file. That is why a hard stop caps the score at 25 rather than zeroing it — an out-of-footprint account that is otherwise excellent is a filing question, and must still outrank a genuinely bad risk."
              >
                only 46% of them
              </Fact>{' '}
              fall inside the filed footprint. Building stock tells the same story:{' '}
              <Fact
                inData="71 of 129 buildings predate 1990; only 19 are 2010 or newer. The range runs 1948 to 2024. 52 of 129 are unsprinklered."
                forAgent="If building age carried heavy weight it would sink most of the queue on its own and flatten the ranking. It is weighted 6 of 100 — real, but not decisive — so the factors with more underwriting signal do the separating."
              >
                most buildings predate the 1990 cut-off
              </Fact>
              , and premium is stranger still:{' '}
              <Fact
                inData="Of 27 property policies, 8 fall in the $50K–$175K acceptable band. 17 are over $175K and 2 under $50K. The median property premium is $262,000 against a target band of $75K–$100K."
                forAgent="The carrier's own written book mostly sits outside its stated premium appetite. So premium is scored but never made a hard stop — treating it as one would have declined the majority of business this book has historically accepted."
              >
                two thirds of written property premium
              </Fact>{' '}
              sits outside the band the guidelines call acceptable.
            </p>
            <p>
              Construction is the one factor where the data is kinder than expected.{' '}
              <Fact
                inData="Fire Resistive 21, Non-Combustible 19, Frame 19, Masonry Non-Combustible 17, Joisted Masonry 15, Modified Fire Resistive 15, Wood Frame 14, Steel Frame 9. Combustible classes total 33 of 129."
                forAgent="Fire Resistive is the largest single class and the appetite table never names it. It outranks every class the table does name on the ISO ladder, so grading it unacceptable would invert the rule's intent. The agent grades it acceptable and says so in the note wherever it applies."
              >
                Fire Resistive is the most common class
              </Fact>{' '}
              of the eight present — and it is the one class the guidelines forgot to mention.
            </p>
            <p style={{ marginBottom: 4 }}>
              Concentration matters as much as the individual risk.{' '}
              <Fact
                inData="California carries 32.1% of bound and active premium — $205.5M across 15 policies and 9 accounts. Florida follows at 20.5%, Illinois at 16.7%."
                forAgent="Five of the six open property submissions are Californian. Each one scores well on the state factor while quietly deepening the book's largest concentration, so the Portfolio tab shows book share beside the queue rather than scoring submissions in isolation."
              >
                California alone is nearly a third of the book
              </Fact>
              , which is awkward given where the live queue is coming from.
            </p>
          </section>

          <section>
            <p className="kicker">Claim</p>
            <h2>Most of the loss has not been paid yet</h2>
            <p>
              The 179 claims carry{' '}
              <Fact
                inData="Total incurred $65.7M — $25.5M paid, $40.2M held in reserves. Open claims alone hold $30.9M in reserves against $8.2M paid. 113 of 179 claims are open; 35 are litigated."
                forAgent="Scoring paid loss alone would see a quarter of the real exposure and flatter exactly the accounts with large claims still developing. The agent scores incurred — paid plus outstanding reserves — which is what an underwriter reads."
              >
                $65.7M of incurred loss
              </Fact>
              , but under forty percent of that has actually been paid. On open claims the ratio is
              starker: four dollars are reserved for every dollar paid out.
            </p>
            <p>
              Getting at any of it takes care, because{' '}
              <Fact
                inData="Claim has policy, coverage and exposure_unit references but no insured field. The account link runs Claim.policy → Policy.insured, which only exists once the policy reference is hydrated."
                forAgent="A clause on policy.insured has to run after expansion, which means `filter`, not `where`. The date cut-off stays in `where`, where it can narrow the scan first. Getting these two stages the wrong way round returns zero rows with no error."
              >
                Claim has no account field at all
              </Fact>
              . And the losses are not all relevant: a claim is only meaningful against the line
              being underwritten, which the appetite table does not say but any property underwriter
              assumes.
            </p>
            <div className="callout" style={{ marginBottom: 4 }}>
              <h3>Worked example</h3>
              <p>
                Lakeside Medical Group carries <strong>$4.82M</strong> of incurred loss across all
                lines. Against a <em>property</em> submission, only <strong>$701K</strong> of that is
                property loss. Scoring the account-wide figure would have declined a submission on
                the strength of somebody else's health claims, so the agent scores the line and
                discloses the remainder in the note.
              </p>
            </div>
          </section>

          <section>
            <p className="kicker">Submission.decline_reason</p>
            <h2>The data ships its own answer key</h2>
            <p>
              Fourteen submissions were declined with a stated reason — a small labelled set showing
              what this carrier actually turns away, and how little of it the appetite table encodes.
            </p>

            <table className="grid" style={{ margin: '4px 0 20px' }}>
              <tbody>
                {DECLINES.map(([n, name, gloss]) => (
                  <tr key={name}>
                    <td className="num" style={{ width: 28, color: 'var(--accent-2)', fontWeight: 600 }}>{n}</td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12.5 }}>{name}</td>
                    <td style={{ color: 'var(--ink-3)', textAlign: 'right' }}>{gloss}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p style={{ marginBottom: 4 }}>
              Only{' '}
              <Fact
                inData="Both outside_appetite declines are health submissions. Of the 14 declined, one is property; the rest are health 5, cgl 3, auto 2, cyber 2 and lpl 1."
                forAgent="A scorer built strictly to the appetite table would agree with two of fourteen real declines. The rest turned on controls, loss development and accumulation — which is the honest case for showing confidence and reasoning rather than presenting a score as a verdict."
              >
                two of the fourteen
              </Fact>{' '}
              were declined for being outside appetite as the guidelines define it. The most common
              reason, insufficient controls, has no representation in the scoring table at all — the
              underlying signals exist in the data, on{' '}
              <Fact
                inData="ExposureUnit.digital_asset.controls carries mfa, edr, siem, offline_backups, pen_test_annual and training as booleans. Building.sprinklered is the property equivalent: 52 of 129 buildings are unsprinklered."
                forAgent="These are the clearest extension point. Sprinkler protection and protection_class are property controls the appetite table omits but every real underwriter weighs, and they are already sitting in the dataset ready to score."
              >
                control fields the guidelines never reference
              </Fact>
              .
            </p>
          </section>

          <section>
            <p className="kicker">Reading the whole thing back</p>
            <h2>What the data changed</h2>
            <p>
              Seven findings did most of the design work. Each one is a property of this dataset,
              not a preference.
            </p>

            <div className="ledger">
              <div className="row head">
                <span>In the data</span>
                <span>In the agent</span>
              </div>
              {LEDGER.map(([found, did]) => (
                <div className="row" key={found}>
                  <span>{found}</span>
                  <span className="did">{did}</span>
                </div>
              ))}
            </div>

            <p style={{ marginTop: 22, marginBottom: 4 }}>
              One last quirk worth recording, because it is the API and not the data:{' '}
              <Fact
                inData="Every grouped query returns rows equal to total — one row per policy — regardless of what is passed to `over`. The documented behaviour is that `over` partitions rows; in practice `id` stays in the partition key."
                forAgent="The agent detects the condition at runtime by comparing row count to total, recomputes the rollup client-side, and records the fallback in its reasoning trace rather than reporting numbers it knows are wrong."
              >
                the <code>over</code> stage never collapses groups
              </Fact>{' '}
              on this deployment. Trusting it would have put confidently incorrect concentration
              figures in front of an underwriter.
            </p>
          </section>
        </div>
      </FactProvider>
    </div>
  )
}
