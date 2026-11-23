import { Route, Routes } from 'react-router';
import { DemoAuthProvider } from './auth/DemoAuthProvider';
import { Layout } from './components/Layout';
import { paths } from './navigation';
import { AdminScreen } from './screens/AdminScreen';
import { LoginScreen, RegisterScreen } from './screens/AuthScreens';
import { CompareScreen } from './screens/CompareScreen';
import { HomeScreen, NotFoundScreen } from './screens/HomeScreen';
import { HospitalsScreen } from './screens/HospitalsScreen';
import { ResultScreen } from './screens/ResultScreen';
import { SupportScreen } from './screens/SupportScreen';
import { TreatmentScreen } from './screens/TreatmentScreen';
import { UploadScreen } from './screens/UploadScreen';

export function App() {
  return (
    <DemoAuthProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path={paths.home} element={<HomeScreen />} />
          <Route path={paths.login} element={<LoginScreen />} />
          <Route path={paths.register} element={<RegisterScreen />} />
          <Route path={paths.upload} element={<UploadScreen />} />
          <Route path={paths.result} element={<ResultScreen />} />
          <Route path={paths.compare} element={<CompareScreen />} />
          <Route path={paths.hospitals} element={<HospitalsScreen />} />
          <Route path={paths.treatment} element={<TreatmentScreen />} />
          <Route path={paths.support} element={<SupportScreen />} />
          <Route path={paths.admin} element={<AdminScreen />} />
          <Route path="*" element={<NotFoundScreen />} />
        </Route>
      </Routes>
    </DemoAuthProvider>
  );
}
