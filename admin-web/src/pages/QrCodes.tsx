import { Link, useParams } from 'react-router-dom';
import { useToast } from '../components/Toast';
import { Button, Card, CopyButton, Empty, ErrorBox, Loading, PageHeader } from '../components/ui';
import { useQrLinks } from '../lib/queries';

const qrSrc = (id: number, format: 'svg' | 'png', scale?: number) =>
  `/api/campuses/${id}/qr?format=${format}${scale ? `&scale=${scale}` : ''}`;

export function QrCodesPage() {
  const q = useQrLinks();
  const toast = useToast();
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  return (
    <div>
      <PageHeader title="QR codes" description="Print these for seat backs, slides and the welcome desk." />
      {q.data.length === 0 ? (
        <Empty>No campuses.</Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {q.data.map((l) => (
            <Card key={l.campus_id} title={l.name}>
              <div className="flex justify-center">
                <img src={qrSrc(l.campus_id, 'svg')} alt={`QR code for ${l.url}`} className="h-52 w-52 rounded border border-gray-100 bg-white" />
              </div>
              <div className="mt-3 flex items-center gap-2 rounded-md bg-gray-50 p-2">
                <a href={l.url} target="_blank" rel="noopener noreferrer" className="flex-1 break-all font-mono text-xs text-indigo-700 hover:underline">
                  {l.url}
                </a>
                <CopyButton text={l.url} onCopied={() => toast.success('URL copied')} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <a
                  href={qrSrc(l.campus_id, 'png', 20)}
                  download={`captions-${l.slug}.png`}
                  className="inline-flex items-center rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-800 shadow-sm hover:bg-gray-50"
                >
                  Download PNG
                </a>
                <a
                  href={qrSrc(l.campus_id, 'svg')}
                  download={`captions-${l.slug}.svg`}
                  className="inline-flex items-center rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-800 shadow-sm hover:bg-gray-50"
                >
                  Download SVG
                </a>
                <Link
                  to={`/print/qr/${l.campus_id}`}
                  target="_blank"
                  className="inline-flex items-center rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700"
                >
                  Print
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/** Print-friendly page: /print/qr/:campusId (no app chrome; print button, no inline script). */
export function PrintQrPage() {
  const { campusId } = useParams();
  const q = useQrLinks();
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const link = q.data.find((l) => String(l.campus_id) === campusId);
  if (!link) return <Empty>Campus not found.</Empty>;
  return (
    <div className="min-h-screen bg-white">
      <div className="flex justify-center gap-2 p-4 print:hidden">
        <Button variant="primary" onClick={() => window.print()}>
          Print
        </Button>
        <Link to="/qr" className="inline-flex items-center rounded-md px-3.5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">
          Back
        </Link>
      </div>
      <div className="mx-auto flex max-w-xl flex-col items-center px-8 pb-12 pt-4 text-center print:pt-16">
        <h1 className="text-4xl font-bold text-gray-900">{link.name}</h1>
        <p className="mt-3 text-xl text-gray-700">Live captions &amp; translation</p>
        <img src={qrSrc(link.campus_id, 'svg', 20)} alt={`QR code for ${link.url}`} className="my-8 h-96 w-96" />
        <p className="text-lg text-gray-700">Scan with your phone camera, or visit</p>
        <p className="mt-1 break-all font-mono text-2xl font-semibold text-gray-900">{link.url.replace(/^https?:\/\//, '')}</p>
      </div>
    </div>
  );
}
