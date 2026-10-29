import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Terms · reScrub" };

export default function TermsPage() {
  return (
    <LegalPage title="Terms of use" updated="October 18, 2026">
      <section>
        <h2>What reScrub is</h2>
        <p>
          reScrub is a training tool. It helps an instructor or trainee review a recorded practice
          procedure by suggesting moments that may show a break in sterile technique.
        </p>
        <p>
          It is for education only. reScrub does not detect microbes, certify that anything is
          sterile, diagnose infection, or establish that contamination occurred. It is not a medical
          device and must not be used to make clinical or patient-care decisions.
        </p>
      </section>

      <section>
        <h2>Who may use it</h2>
        <p>
          reScrub is available to instructors and trainees with an account, created on the sign-up
          page (if this site allows it) or by the site’s administrator. Keep your password private
          and sign out on shared computers. The demonstration is open to anyone.
        </p>
      </section>

      <section>
        <h2>Human review is required</h2>
        <p>
          Findings are proposed by computer-vision software that tracks people, hands, and surfaces
          from a single camera, and they can be wrong. It can flag moments where nothing went wrong
          and miss moments that matter, especially when the view is blocked or it is unclear
          whether a hand touched or hovered. A person must watch each moment and make the decision.
          Confirm and Dismiss record that person’s judgment, not the software’s.
        </p>
      </section>

      <section>
        <h2>What you may upload</h2>
        <ul>
          <li>Only recordings you have permission to use and share for this purpose.</li>
          <li>
            Simulated procedures (mannequins, practice stations, staged mistakes) or footage that has
            been properly de-identified.
          </li>
          <li>
            No footage that shows identifiable patients, names, wristbands, screens, or other health
            information.
          </li>
        </ul>
        <p>
          Checking the acknowledgment box records your statement that you have permission. It does
          not make processing patient video compliant with HIPAA or any other law.
        </p>
      </section>

      <section>
        <h2>Accounts and uploads that break these terms</h2>
        <p>
          Administrators may disable an account, or delete its recordings, if it is used to upload
          footage that is not allowed above or to interfere with the service.
        </p>
      </section>

      <section>
        <h2>Service</h2>
        <p>
          reScrub is provided as-is, without warranties. Recordings and results are kept as
          described in the{" "}
          <Link href="/privacy" className="text-accent underline underline-offset-2">
            Privacy notes
          </Link>
          . For questions about these terms or your account, contact this site’s administrator.
        </p>
      </section>
    </LegalPage>
  );
}
