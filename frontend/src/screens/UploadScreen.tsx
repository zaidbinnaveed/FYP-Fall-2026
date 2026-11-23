import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { api } from '../api';
import { resultPath } from '../navigation';
import { ACCEPTED_TYPES, validateUpload } from '../domain/upload';
import { strings } from '../strings';

/** UC-SCR-01 (mock): nothing is uploaded; the file name picks a sample case. */
export function UploadScreen() {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const cases = useQuery({ queryKey: ['sample-cases'], queryFn: () => api.listSampleCases() });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = validateUpload(file);
    setError(problem);
    if (problem || !file) return;
    await navigate(resultPath(api.caseForFileName(file.name)), {
      state: { fileName: file.name },
    });
  }

  return (
    <>
      <title>{`${strings.uploadHeading} — ${strings.appName}`}</title>
      <h1>{strings.uploadHeading}</h1>
      <p>{strings.uploadIntro}</p>
      <form className="form" onSubmit={(e) => void onSubmit(e)} noValidate>
        <label htmlFor="upload-file">{strings.uploadFileLabel}</label>
        <input
          id="upload-file"
          type="file"
          accept={ACCEPTED_TYPES.join(',')}
          aria-describedby="upload-rule"
          aria-invalid={error ? true : undefined}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setError(null);
          }}
        />
        <p id="upload-rule" className="note">
          {strings.uploadFileRule}
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="button">
          {strings.uploadSubmit}
        </button>
      </form>

      <h2>{strings.samplesHeading}</h2>
      {cases.isPending ? (
        <p>{strings.loading}</p>
      ) : (
        <ul className="card-list">
          {(cases.data ?? []).map((c) => (
            <li key={c.id} className="card">
              <Link to={resultPath(c.id)}>{strings.sampleChoose(c.title)}</Link>
              <p>{c.description}</p>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
